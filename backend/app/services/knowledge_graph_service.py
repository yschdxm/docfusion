from typing import List, Dict, Any
from app.db.neo4j_db import run_cypher
from app.services.llm_service import llm_service
import logging
import asyncio

logger = logging.getLogger(__name__)


class KnowledgeGraphService:

    @staticmethod
    def _sanitize_label(label: str) -> str:
        """将 type 值清洗为安全的 Neo4j label（仅字母数字下划线，大写开头）。"""
        safe = "".join(c if c.isalnum() else "_" for c in label).strip("_")
        if not safe:
            return "Other"
        return safe[0].upper() + safe[1:] if len(safe) > 1 else safe.upper()

    async def build_graph_from_entities(
        self,
        document_id: str,
        entities: List[Dict[str, Any]],
        relations: List[Dict[str, Any]] = None,
    ):
        """从提取的实体和关系构建知识图谱。

        多文档共享实体时：属性追加不覆盖，document_ids 累积。
        type 作为 Neo4j label 存储（如 :Location, :Person），不再使用 :Entity 通用 label。
        """
        # 标准化实体格式
        normalized_entities = []
        for e in entities:
            if "name" in e:
                normalized_entities.append(e)
            elif "entity_name" in e:
                normalized_entities.append({
                    "name": e["entity_name"],
                    "type": e.get("entity_type", "OTHER"),
                    "attributes": {
                        "value": e.get("entity_value", ""),
                        "context": e.get("context", ""),
                    }
                })

        # 按 type 分组，每组用对应的 label 写入
        batch_size = 100
        type_groups: Dict[str, List[Dict]] = {}
        for entity in normalized_entities:
            raw_type = entity.get("type", "OTHER") or "OTHER"
            label = self._sanitize_label(raw_type)
            if label not in type_groups:
                type_groups[label] = []

            attrs = entity.get("attributes", {})
            ent = {
                "name": entity.get("name", ""),
                "doc_id": document_id,
            }
            # 添加日志：显示原始attributes
            if attrs:
                logger.debug("[KG-BUILD] 实体 %s (type=%s) 有 %d 个attributes: %s",
                           entity.get("name", "N/A"), raw_type, len(attrs), list(attrs.keys()))
                for key, val in attrs.items():
                    safe_key = "".join(c if c.isalnum() else "_" for c in key)
                    if safe_key and val:
                        ent[safe_key] = str(val)[:500]
                        logger.debug("[KG-BUILD]   - %s -> %s: %s", key, safe_key, str(val)[:50])
            else:
                logger.debug("[KG-BUILD] 实体 %s (type=%s) 没有attributes",
                           entity.get("name", "N/A"), raw_type)
            type_groups[label].append(ent)

        # 汇总日志
        total_entities = sum(len(entities) for entities in type_groups.values())
        logger.info("[KG-BUILD] 准备写入 %d 个实体到Neo4j，共 %d 种类型",
                   total_entities, len(type_groups))
        for label, entities_list in type_groups.items():
            # 统计有属性的实体数量
            with_attrs = sum(1 for e in entities_list if len(e) > 2)  # name + doc_id + 至少1个属性
            logger.info("[KG-BUILD] 类型 %s: %d 个实体，%d 个有额外属性",
                       label, len(entities_list), with_attrs)

        for label, entities_list in type_groups.items():
            for batch_start in range(0, len(entities_list), batch_size):
                batch = entities_list[batch_start:batch_start + batch_size]
                try:
                    # 为每个实体单独处理，确保所有属性都被写入
                    for ent in batch:
                        # 构建属性字典（排除name和doc_id）
                        props = {k: v for k, v in ent.items() if k not in ['name', 'doc_id']}

                        await run_cypher(
                            f"""
                            MERGE (n:{label} {{name: $name}})
                            ON CREATE SET n = $props, n.name = $name, n.document_ids = [$doc_id]
                            ON MATCH SET n += $props, n.document_ids = CASE WHEN $doc_id IN n.document_ids THEN n.document_ids ELSE n.document_ids + $doc_id END
                            """,
                            {"name": ent['name'], "doc_id": ent['doc_id'], "props": props}
                        )
                    logger.debug("[KG-BUILD] 成功写入 %d 个 %s 类型实体", len(batch), label)
                except Exception as ex:
                    logger.warning(f"批量写入实体失败 (label={label}): {ex}")

        # 写入文档节点
        await run_cypher(
            """
            MERGE (d:Document {id: $doc_id})
            SET d.entity_count = $count
            """,
            {"doc_id": document_id, "count": len(normalized_entities)}
        )

        # 批量写入关系
        if relations:
            entity_names = {e.get("name") for e in normalized_entities}

            # 确保关系涉及的实体存在
            missing_entities = set()
            for rel in relations:
                for name in [rel.get("head", rel.get("source", "")), rel.get("tail", rel.get("target", ""))]:
                    if name and name not in entity_names:
                        missing_entities.add(name)

            if missing_entities:
                missing_list = [{"name": n, "doc_id": document_id} for n in missing_entities]
                try:
                    await run_cypher(
                        """
                        UNWIND $entities AS ent
                        MERGE (n:Other {name: ent.name})
                        ON CREATE SET n.document_ids = [ent.doc_id]
                        ON MATCH SET n.document_ids = CASE WHEN ent.doc_id IN n.document_ids THEN n.document_ids ELSE n.document_ids + ent.doc_id END
                        """,
                        {"entities": missing_list}
                    )
                except Exception:
                    pass

            # 按关系类型分组批量写入
            rel_groups = {}
            for rel in relations:
                rel_type = rel.get("relation", rel.get("relation_type", "RELATED_TO"))
                rel_type = "".join(c if c.isalnum() or c == "_" else "_" for c in rel_type).upper()
                if not rel_type:
                    rel_type = "RELATED_TO"
                if rel_type not in rel_groups:
                    rel_groups[rel_type] = []
                rel_groups[rel_type].append({
                    "source": rel.get("head", rel.get("source", "")),
                    "target": rel.get("tail", rel.get("target", "")),
                    "description": str(rel.get("attributes", rel.get("description", ""))),
                })

            # 并行写入不同关系类型的关系
            async def write_relation_batch(rel_type, rel_list):
                tasks = []
                for batch_start in range(0, len(rel_list), batch_size):
                    batch = rel_list[batch_start:batch_start + batch_size]
                    task = run_cypher(
                        f"""
                        UNWIND $rels AS rel
                        MATCH (a {{name: rel.source}})
                        MATCH (b {{name: rel.target}})
                        MERGE (a)-[r:{rel_type}]->(b)
                        SET r.description = rel.description
                        """,
                        {"rels": batch}
                    )
                    tasks.append(task)

                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    logger.warning(f"批量写入关系失败 ({rel_type}): {e}")

            relation_tasks = [
                write_relation_batch(rel_type, rel_list)
                for rel_type, rel_list in rel_groups.items()
            ]

            if relation_tasks:
                await asyncio.gather(*relation_tasks, return_exceptions=True)

        return {"entities_count": len(normalized_entities), "relations_count": len(relations or [])}

    async def build_graph_from_xlsx(
        self,
        document_id: str,
        sheets: List[Dict[str, Any]],
        document_title: str = None,
    ):
        """从 xlsx 数据构建知识图谱。

        用 AI 分析表头，确定哪些列是主实体、哪些是属性、列间关系，
        然后按行构建实体和关系。
        """
        for sheet in sheets:
            sheet_name = sheet.get("name", "")
            data = sheet.get("data", [])
            if len(data) < 2:
                continue

            headers = data[0]
            data_rows = data[1:]
            valid_headers = [str(h).strip() for h in headers if h and str(h).strip()]
            if not valid_headers:
                continue

            # 统计每列信息
            col_stats = {}
            for col_idx, header in enumerate(headers):
                header_str = str(header).strip() if header and str(header).strip() else ""
                if not header_str:
                    continue
                unique_values = set()
                for row in data_rows:
                    if col_idx < len(row) and row[col_idx]:
                        val = str(row[col_idx]).strip()
                        if val and val not in ("None", "null", "", "—"):
                            unique_values.add(val)
                col_stats[header_str] = {
                    "unique_count": len(unique_values),
                    "sample_values": "、".join(list(unique_values)[:5]),
                }

            # AI 分析表头：确定主实体列、属性列、关系（带重试机制）
            analysis = {}
            max_retries = 3

            for retry_count in range(max_retries):
                try:
                    stats_text = "\n".join([
                        f"- {h}: 唯一值{col_stats[h]['unique_count']}个, 样本: {col_stats[h]['sample_values']}"
                        for h in valid_headers if h in col_stats
                    ])
                    prompt = f"""分析以下表格的表头和数据统计，确定数据结构。

Sheet名：{sheet_name}
表头及统计：
{stats_text}

实体类型参考（动态选择最匹配的）：
通用：Person(人名) Organization(机构) Department(部门) Location(地名) GeographicFeature(地理实体) Date(日期) Duration(时长) TimePeriod(时期) Money(金额) Percentage(百分比) Measurement(度量值) Count(数量) Ranking(排名) Law(法律) Policy(政策) Standard(标准) Contract(合同) Event(事件) Material(物料) Product(产品) Technology(技术) Software(软件/平台) Equipment(设备) AnimalSpecies(动物) PlantSpecies(植物) Food(食品) Nutrient(营养成分)
医疗健康：Disease(疾病) Symptom(症状) Drug(药品) Treatment(治疗方案) MedicalDevice(医疗器械) BodyPart(身体部位) BodySystem(人体系统) Gene(基因) Virus(病毒/病原体) Vaccine(疫苗) MedicalTest(检查项目) HealthIndicator(健康指标) Hospital(医院) MedicalDepartment(科室) TraditionalMedicine(中医药) MentalHealthCondition(心理状况)
气象环境：WeatherEvent(气象事件) ClimateIndicator(气候指标) Pollutant(污染物) EmissionSource(排放源) EcologicalZone(生态区域) Disaster(灾害) EnvironmentalStandard(环境标准) WaterBody(水体) ForestResource(森林资源) SoilType(土壤) AirQualityLevel(空气质量等级)
经济金融：Industry(行业) EconomicIndicator(经济指标) FinancialProduct(金融产品) StockCode(股票代码) Currency(货币) TradeAgreement(贸易协定) TaxType(税种) InvestmentProject(投资项目) SupplyChain(供应链)
交通运输：TransportRoute(交通线路) Vehicle(交通工具) TransportHub(交通枢纽) Infrastructure(基础设施) TransportIndicator(交通指标)
能源矿产：EnergySource(能源) PowerPlant(电站) Mine(矿山) MineralResource(矿产) EnergyIndicator(能源指标)
农业：Crop(农作物) Farmland(农田) AgriculturalProduct(农产品) Fertilizer(肥料) FarmingTechnique(农艺技术) Livestock(畜牧) FisheryResource(渔业资源) AgriculturalMachinery(农机) AgriculturalIndicator(农业指标)
水利：WaterProject(水利工程) WaterResource(水资源) FloodControlMeasure(防洪设施) WaterQualityIndicator(水质指标)
教育：School(学校) Major(专业) Course(课程) Certification(证书) Exam(考试) EducationLevel(学段) ResearchProject(科研课题) AcademicPaper(学术论文) Scholar(学者) ResearchInstitution(科研院所)
文旅：ScenicSpot(景点) CulturalRelic(文物) ArtWork(作品) Festival(节庆) Route(线路) CulturalVenue(文化场馆) IntangibleHeritage(非遗) FolkCustom(民俗)
体育：SportEvent(体育赛事) Athlete(运动员) SportsTeam(运动队) SportVenue(体育场馆) SportRecord(体育记录)
国防军事：MilitaryUnit(军事单位) WeaponSystem(武器装备) MilitaryOperation(军事行动) DefenseProject(国防工程)
法律司法：CourtCase(案件) Court(法院) LegalTerm(法律概念) Penalty(处罚) LegalProcedure(法律程序)
社会民生：SocialProgram(社会项目) WelfareBenefit(福利补贴) PopulationGroup(特定人群) Community(社区)
科技信息：Patent(专利) TechStandard(技术标准) Innovation(创新成果) DataResource(数据资源) Algorithm(算法)
建筑规划：Building(建筑物) UrbanPlan(城市规划) ConstructionProject(在建工程) ArchitecturalStyle(建筑风格)
食品卫生：FoodSafetyStandard(食安标准) FoodAdditive(食品添加剂) NutritionLabel(营养标签) FoodContaminant(食品污染物)

主实体列选择规则（必须严格遵守）：
1. 主实体是每行数据描述的那个"主体"——表格在描述谁的数据
2. 排除以下列作为主实体：
   - 纯数字列（如序号、编号、编码）
   - 日期/时间列
   - 纯数值度量列（如金额、数量、指标值）
3. 主实体应该是有独立语义含义的名称列（如地名、人名、机构名、产品名、事件名等）
4. 如果有多个候选，选择语义上最能代表"这行数据在描述什么"的列
5. 不要选择唯一值过多（如接近总行数的ID列）或过少（如只有1-2个值的列）

列角色定义（必须严格遵守）：
- entity: 独立实体列——值本身是有语义的实体（如地名、人名、机构名、组织名）
- attribute: 属性值列——值是主实体的属性，存储在主实体的 attributes 中，不创建独立节点

属性值列判断规则（必须严格遵守）：
1. 数值列（如监测值、数量、指标值）必须标记为 attribute
2. 时间/日期列必须标记为 attribute
3. 简单的文本描述列标记为 attribute
4. 只有地名、人名、机构名等有独立语义的列才标记为 entity

类型与角色对应关系（必须严格遵守）：
- 以下类型必须标记为 attribute（属性值）：Measurement, Count, Percentage, Money, Date, TimePeriod, Duration, Pollutant, ClimateIndicator, WaterQualityIndicator, HealthIndicator, AirQualityLevel, EconomicIndicator, TransportIndicator, EnergyIndicator, AgriculturalIndicator
- 以下类型可以标记为 entity（独立实体）：Person, Organization, Department, Location, GeographicFeature, ScenicSpot, CulturalRelic, School, Hospital, Industry, Product, Vehicle, Building, Crop, Disease, Drug, Event, Material, Equipment, Software, Technology
- attribute 列的值将作为主实体的属性存储，不会创建独立节点
- entity 列的值将创建独立节点，并建立关系

请分析：
1. 主实体列是哪一列，它是什么类型
2. 其他列的角色（entity=独立实体, attribute=属性值）
3. 列与主实体之间的关系

返回 JSON：
{{
  "primary_entity": {{"column": "主实体列名", "type": "实体类型"}},
  "column_roles": {{
    "列名": {{"role": "entity|attribute", "type": "实体类型", "description": "说明"}}
  }},
  "column_relations": [
    {{"source": "主实体列名", "relation": "关系类型", "target": "属性列名", "target_type": "目标实体类型", "description": "说明"}}
  ]
}}

只返回 JSON。"""

                    logger.info(f"AI 第 {retry_count + 1} 次请求 - Sheet: {sheet_name}, 表头数: {len(valid_headers)}")
                    response = await llm_service.chat_completion(
                        [{"role": "user", "content": prompt}],
                        temperature=0.3,
                        enable_thinking=False
                    )

                    logger.info(f"AI 第 {retry_count + 1} 次响应 - 类型: {type(response)}, 长度: {len(response) if response else 0}")
                    if not response:
                        logger.warning(f"AI 第 {retry_count + 1} 次返回空响应 (response is None or empty)")
                        if retry_count < max_retries - 1:
                            continue
                        analysis = {}
                        break

                    json_str = response.strip()
                    logger.debug(f"AI 第 {retry_count + 1} 次响应: {json_str[:200]}...")

                    if "```json" in json_str:
                        json_str = json_str.split("```json")[1].split("```")[0].strip()
                    elif "```" in json_str:
                        json_str = json_str.split("```")[1].strip()

                    import json
                    if not json_str:
                        logger.warning(f"AI 第 {retry_count + 1} 次响应提取后为空")
                        if retry_count < max_retries - 1:
                            continue
                        analysis = {}
                        break

                    analysis = json.loads(json_str)
                    logger.info(f"AI 第 {retry_count + 1} 次分析成功")
                    break

                except json.JSONDecodeError as e:
                    logger.warning(f"AI 第 {retry_count + 1} 次返回无效JSON: {e}")
                    if retry_count < max_retries - 1:
                        logger.info(f"重试第 {retry_count + 2} 次...")
                        continue
                    analysis = {}
                except Exception as e:
                    logger.warning(f"AI 第 {retry_count + 1} 次分析失败: {e}")
                    if retry_count < max_retries - 1:
                        logger.info(f"重试第 {retry_count + 2} 次...")
                        continue
                    analysis = {}

            primary_entity = analysis.get("primary_entity", {})
            column_roles = analysis.get("column_roles", {})
            column_relations = analysis.get("column_relations", [])

            primary_col = primary_entity.get("column", "")
            primary_type = primary_entity.get("type", "OTHER")

            # 找到主实体列和各列的索引
            primary_col_idx = None
            col_idx_map = {}
            for col_idx, header in enumerate(headers):
                h = str(header).strip() if header and str(header).strip() else ""
                if h:
                    col_idx_map[h] = col_idx
                    if h == primary_col:
                        primary_col_idx = col_idx

            # 如果没有明确的主实体列，默认用第一列
            if primary_col_idx is None and valid_headers:
                primary_col = valid_headers[0]
                primary_col_idx = col_idx_map.get(primary_col, 0)
                primary_type = column_roles.get(primary_col, {}).get("type", "OTHER")

            # 按行构建实体和关系
            all_entities = []
            all_relations = []
            seen_entities = set()

            # 判断列是否应该作为独立实体
            def should_create_independent_entity(col_name, col_role_info, value):
                if not value or len(value) < 2:
                    return False
                role = col_role_info.get("role", "attribute")
                if role == "attribute":
                    return False
                if role == "entity":
                    return True
                return False

            for row in data_rows:
                if primary_col_idx is None or primary_col_idx >= len(row):
                    continue
                entity_val = row[primary_col_idx]
                if not entity_val or str(entity_val).strip() in ("", "None", "null", "—"):
                    continue
                entity_name = str(entity_val).strip()

                if entity_name not in seen_entities:
                    seen_entities.add(entity_name)
                    all_entities.append({
                        "name": entity_name,
                        "type": primary_type,
                        "attributes": {"source_column": primary_col, "sheet": sheet_name},
                    })

                for rel_def in column_relations:
                    target_col = rel_def.get("target", "")
                    rel_type = rel_def.get("relation", "HAS_VALUE")
                    target_type = rel_def.get("target_type", "OTHER")
                    target_role_info = column_roles.get(target_col, {})

                    target_col_idx = col_idx_map.get(target_col)
                    if target_col_idx is None or target_col_idx >= len(row):
                        continue
                    target_val = row[target_col_idx]
                    if not target_val or str(target_val).strip() in ("", "None", "null", "—"):
                        continue
                    target_value = str(target_val).strip()

                    if should_create_independent_entity(target_col, target_role_info, target_value):
                        if target_value not in seen_entities:
                            seen_entities.add(target_value)
                            all_entities.append({
                                "name": target_value,
                                "type": target_type,
                                "attributes": {"source_column": target_col, "sheet": sheet_name},
                            })

                        all_relations.append({
                            "head": entity_name,
                            "relation": rel_type,
                            "tail": target_value,
                            "attributes": {"column": target_col},
                        })
                    else:
                        for entity in all_entities:
                            if entity.get("name") == entity_name:
                                if "attributes" not in entity:
                                    entity["attributes"] = {}
                                safe_key = "".join(c if c.isalnum() or c == "_" else "_" for c in target_col)
                                if safe_key:
                                    entity["attributes"][safe_key] = target_value
                                break

            if all_entities:
                await self.build_graph_from_entities(document_id, all_entities, all_relations)

    async def get_graph(
        self,
        limit: int = 500,
        document_id: str = None,
        user_doc_ids: List[str] = None
    ) -> Dict[str, Any]:
        """获取图谱数据，返回所有类型节点。支持按文档 ID 过滤。"""
        if document_id:
            nodes_result = await run_cypher(
                """
                MATCH (n)
                WHERE n.document_ids IS NOT NULL AND $doc_id IN n.document_ids
                  AND NOT n:Document
                RETURN n.name AS name, labels(n)[0] AS type, n.value AS value, n.document_ids AS document_ids
                LIMIT $limit
                """,
                {"doc_id": document_id, "limit": limit}
            )

            edges_result = await run_cypher(
                """
                MATCH (a)-[r]->(b)
                WHERE a.document_ids IS NOT NULL AND b.document_ids IS NOT NULL
                  AND $doc_id IN a.document_ids AND $doc_id IN b.document_ids
                  AND NOT a:Document AND NOT b:Document
                RETURN a.name AS source, b.name AS target, type(r) AS type, r.description AS description
                LIMIT $limit
                """,
                {"doc_id": document_id, "limit": limit}
            )
        elif user_doc_ids is not None:
            nodes_result = await run_cypher(
                """
                MATCH (n)
                WHERE n.document_ids IS NOT NULL AND NOT n:Document
                  AND any(did IN $user_doc_ids WHERE did IN n.document_ids)
                RETURN n.name AS name, labels(n)[0] AS type, n.value AS value, n.document_ids AS document_ids
                LIMIT $limit
                """,
                {"user_doc_ids": user_doc_ids, "limit": limit}
            )

            edges_result = await run_cypher(
                """
                MATCH (a)-[r]->(b)
                WHERE a.document_ids IS NOT NULL AND b.document_ids IS NOT NULL
                  AND NOT a:Document AND NOT b:Document
                  AND any(did IN $user_doc_ids WHERE did IN a.document_ids)
                  AND any(did IN $user_doc_ids WHERE did IN b.document_ids)
                RETURN a.name AS source, b.name AS target, type(r) AS type, r.description AS description
                LIMIT $limit
                """,
                {"user_doc_ids": user_doc_ids, "limit": limit}
            )
        else:
            # 无过滤条件时不返回任何数据（安全兜底）
            return {"nodes": [], "edges": []}

        nodes = [
            {
                "id": r["name"],
                "name": r["name"],
                "type": r["type"] or "Other",
                "value": r.get("value") or "",
                "document_ids": r.get("document_ids") or []
            }
            for r in nodes_result
        ]

        edges = [
            {"source": r["source"], "target": r["target"], "type": r["type"] or "", "description": r.get("description") or ""}
            for r in edges_result
        ]

        return {"nodes": nodes, "edges": edges}

    async def query_graph(self, query: str, user_doc_ids: List[str] = None) -> Dict[str, Any]:
        if user_doc_ids is not None:
            search_result = await run_cypher(
                """
                MATCH (n)
                WHERE (n.name CONTAINS $query OR n.value CONTAINS $query)
                  AND n.document_ids IS NOT NULL AND NOT n:Document
                  AND any(did IN $user_doc_ids WHERE did IN n.document_ids)
                RETURN n.name AS name, labels(n)[0] AS type, n.value AS value, n.context AS context
                LIMIT 20
                """,
                {"query": query, "user_doc_ids": user_doc_ids}
            )
        else:
            # 无过滤条件时不返回任何数据（安全兜底）
            search_result = []

        related_entities = [
            {
                "name": r["name"],
                "type": r["type"] or "Other",
                "value": r.get("value") or "",
                "context": r.get("context") or ""
            }
            for r in search_result
        ]

        if related_entities:
            context = "\n".join([
                f"- {e['name']} ({e['type']}): {e.get('value', '')}"
                for e in related_entities
            ])

            prompt = f"""基于以下知识图谱信息回答用户问题。

知识图谱相关信息：
{context}

用户问题：{query}

请根据提供的信息回答问题。"""

            messages = [{"role": "user", "content": prompt}]
            answer = await llm_service.chat_completion(messages, temperature=0.5, enable_thinking=False)
        else:
            answer = "未找到相关实体信息。"

        return {
            "answer": answer,
            "related_entities": related_entities
        }

    async def query_for_field(
        self,
        field_name: str,
        entity_names: List[str] = None,
        doc_ids: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """字段级图谱查询。"""
        results = []

        doc_filter = ""
        params = {"field": field_name}
        if doc_ids is not None:
            doc_filter = "AND any(did IN $doc_ids WHERE did IN n.document_ids)"
            params["doc_ids"] = doc_ids
        else:
            # 无文档过滤时不查询（安全兜底）
            return results

        field_result = await run_cypher(
            f"""
            MATCH (n)
            WHERE (n.name CONTAINS $field OR n.value CONTAINS $field)
              AND n.document_ids IS NOT NULL AND NOT n:Document
              {doc_filter}
            RETURN n.name AS name, labels(n)[0] AS type, n.value AS value, n.context AS context
            LIMIT 10
            """,
            params
        )

        for r in field_result:
            entity_type = r["type"] or "Other"
            text = f"{r['name']} ({entity_type}): {r.get('value') or ''}"
            if r.get("context"):
                text += f" [上下文: {r['context'][:200]}]"
            results.append({"content": text, "source": "neo4j_field"})

        if entity_names:
            for name in entity_names[:3]:
                if not name or len(name) < 2:
                    continue
                entity_params = {"name": name}
                entity_doc_filter = ""
                if doc_ids is not None:
                    entity_doc_filter = "AND any(did IN $doc_ids WHERE did IN other.document_ids)"
                    entity_params["doc_ids"] = doc_ids

                entity_result = await run_cypher(
                    f"""
                    MATCH (n {{name: $name}})-[r]-(other)
                    WHERE other.document_ids IS NOT NULL AND NOT other:Document
                      {entity_doc_filter}
                    RETURN other.name AS name, labels(other)[0] AS type, other.value AS value, type(r) AS rel_type
                    LIMIT 10
                    """,
                    entity_params
                )
                for r in entity_result:
                    other_type = r["type"] or "Other"
                    text = f"{name} --[{r['rel_type']}]--> {r['name']} ({other_type}): {r.get('value') or ''}"
                    results.append({"content": text, "source": "neo4j_entity"})

        return results

    async def delete_document_entities(self, document_id: str):
        """删除文档关联的实体，从 document_ids 中移除，空列表才删除节点。"""
        # 移除 document_id
        await run_cypher(
            """
            MATCH (n)
            WHERE n.document_ids IS NOT NULL AND $doc_id IN n.document_ids
              AND NOT n:Document
            SET n.document_ids = [x IN n.document_ids WHERE x <> $doc_id]
            """,
            {"doc_id": document_id}
        )
        # 删除无归属的实体
        await run_cypher(
            """
            MATCH (n)
            WHERE n.document_ids IS NOT NULL AND size(n.document_ids) = 0
              AND NOT n:Document
            DETACH DELETE n
            """,
            {}
        )
        # 删除文档节点
        await run_cypher(
            "MATCH (d:Document {id: $doc_id}) DETACH DELETE d",
            {"doc_id": document_id}
        )


knowledge_graph_service = KnowledgeGraphService()
