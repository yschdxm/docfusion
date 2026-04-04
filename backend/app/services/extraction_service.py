import logging
from typing import List, Dict, Any, Optional, Callable
from uuid import UUID
import asyncio
import json
from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
from app.db.mongodb import get_collection

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "md": MdParser(),
            "txt": TxtParser()
        }
    
    async def extract_from_document(
        self,
        file_path: str,
        file_type: str,
        entity_types: Optional[List[str]] = None,
        custom_fields: Optional[List[str]] = None,
        progress_callback: Optional[Callable] = None,
        base_progress: int = 0,
        progress_range: int = 100
    ) -> Dict[str, Any]:
        parser = self.parsers.get(file_type)
        if not parser:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        if progress_callback:
            await progress_callback("正在解析文档...", f"{base_progress}%")
        
        parsed_data = parser.parse(file_path)
        full_text = parsed_data.get("full_text", "")
        text_length = len(full_text)
        
        all_entities = []
        
        CHUNK_SIZE = 200000  # 200K 字符/块
        
        if file_type == "xlsx":
            # Excel 文件特殊处理：AI 分析表头和样本，然后批量提取
            if progress_callback:
                await progress_callback("正在分析表格结构...", f"{base_progress + 10}%")
            
            sheets = parsed_data.get("sheets", [])
            
            for sheet in sheets:
                sheet_name = sheet.get("name", "")
                sheet_data = sheet.get("data", [])
                
                if not sheet_data or len(sheet_data) < 2:
                    continue
                
                # 提取表头
                headers = sheet_data[0]
                
                # 采样：前10行 + 末5行
                sample_start = sheet_data[1:11] if len(sheet_data) > 1 else []
                sample_end = sheet_data[-5:] if len(sheet_data) > 15 else []
                sample_rows = sample_start + sample_end
                
                # 构建样本文本（Markdown表格格式）
                valid_headers = [str(h) for h in headers if h]
                sample_text = "| " + " | ".join(valid_headers) + " |\n"
                sample_text += "| " + " | ".join(["---"] * len(valid_headers)) + " |\n"
                for row in sample_rows:
                    row_cells = [str(cell) if cell else "" for cell in row[:len(headers)]]
                    sample_text += "| " + " | ".join(row_cells) + " |\n"
                
                # 添加表头作为实体
                for header in headers:
                    if header and str(header).strip():
                        all_entities.append({
                            "entity_type": "TABLE_HEADER",
                            "entity_name": str(header).strip(),
                            "entity_value": str(header).strip(),
                            "context": f"Sheet: {sheet_name}"
                        })
                
                if progress_callback:
                    await progress_callback(f"正在使用AI分析 {sheet_name} 表格...", f"{base_progress + 20}%")
                
                # 让 AI 分析样本，提取关键实体
                analysis_prompt = f"""分析以下Excel表格结构，识别关键实体。

表格名称：{sheet_name}
表头：{', '.join(valid_headers)}
总行数：{len(sheet_data) - 1} 行数据

数据样本（前10行+末5行）：
{sample_text}

请提取以下实体：
1. 表格中出现的地点名称（城市、省份、地区等）
2. 表格中出现的人名
3. 表格中出现的机构名称
4. 表格中出现的关键数值范围或统计信息
5. 表格中出现的日期或时间范围
6. 其他关键实体

返回JSON格式：
```json
[
    {{
        "entity_type": "LOCATION/PERSON/ORGANIZATION/DATE/NUMBER",
        "entity_name": "实体名称",
        "entity_value": "实体值",
        "context": "上下文说明"
    }}
]
```

只返回JSON，不要其他说明。"""
                
                messages = [{"role": "user", "content": analysis_prompt}]
                response = await llm_service.chat_completion(messages, temperature=0.3)
                
                # 解析 AI 返回的实体
                try:
                    json_str = response.strip()
                    if "```json" in json_str:
                        json_str = json_str.split("```json")[1].split("```")[0].strip()
                    elif "```" in json_str:
                        json_str = json_str.split("```")[1].strip()
                    ai_entities = json.loads(json_str)
                    all_entities.extend(ai_entities)
                except Exception as e:
                    logger.warning("AI entity parsing error: %s", e)
                
                # 批量提取所有行的结构化数据（不需要调用AI）
                if progress_callback:
                    await progress_callback(f"正在批量提取 {sheet_name} 数据...", f"{base_progress + 50}%")
                
                # 识别关键列类型
                location_cols = []
                number_cols = []
                date_cols = []
                
                location_keywords = ['城市', '地区', '省份', '地点', 'city', 'location', '站点', '区县', 'county']
                date_keywords = ['日期', '时间', 'date', 'time', '年', '月', '日', 'year', 'month']
                number_keywords = ['aqi', 'pm', '浓度', '值', '数量', '总数', '平均', 'value', 'count', 'total']
                
                for idx, header in enumerate(headers):
                    header_str = str(header).lower() if header else ""
                    if any(kw in header_str for kw in location_keywords):
                        location_cols.append(idx)
                    elif any(kw in header_str for kw in date_keywords):
                        date_cols.append(idx)
                    elif any(kw in header_str for kw in number_keywords):
                        number_cols.append(idx)
                
                # 批量提取地点
                for col_idx in location_cols:
                    seen_locations = set()
                    for row in sheet_data[1:]:
                        if col_idx < len(row) and row[col_idx]:
                            location = str(row[col_idx]).strip()
                            if location and location not in seen_locations and location not in ['None', 'null', '']:
                                seen_locations.add(location)
                                all_entities.append({
                                    "entity_type": "LOCATION",
                                    "entity_name": location,
                                    "entity_value": location,
                                    "context": f"Sheet: {sheet_name}, Column: {headers[col_idx]}"
                                })
                
                # 批量提取日期
                for col_idx in date_cols:
                    seen_dates = set()
                    for row in sheet_data[1:]:
                        if col_idx < len(row) and row[col_idx]:
                            date_val = str(row[col_idx]).strip()
                            if date_val and date_val not in seen_dates and date_val not in ['None', 'null', '']:
                                seen_dates.add(date_val)
                                all_entities.append({
                                    "entity_type": "DATE",
                                    "entity_name": f"{headers[col_idx]}: {date_val}",
                                    "entity_value": date_val,
                                    "context": f"Sheet: {sheet_name}"
                                })
                
                # 为数值列添加统计信息
                for col_idx in number_cols:
                    if col_idx < len(headers):
                        values = []
                        for row in sheet_data[1:]:
                            if col_idx < len(row) and row[col_idx]:
                                try:
                                    val_str = str(row[col_idx]).replace(',', '').replace(' ', '')
                                    val = float(val_str)
                                    values.append(val)
                                except:
                                    pass
                        
                        if values:
                            col_name = str(headers[col_idx])
                            all_entities.extend([
                                {
                                    "entity_type": "NUMBER",
                                    "entity_name": f"{col_name}_最大值",
                                    "entity_value": str(max(values)),
                                    "context": f"Sheet: {sheet_name}"
                                },
                                {
                                    "entity_type": "NUMBER",
                                    "entity_name": f"{col_name}_最小值",
                                    "entity_value": str(min(values)),
                                    "context": f"Sheet: {sheet_name}"
                                },
                                {
                                    "entity_type": "NUMBER",
                                    "entity_name": f"{col_name}_平均值",
                                    "entity_value": f"{sum(values)/len(values):.2f}",
                                    "context": f"Sheet: {sheet_name}"
                                },
                                {
                                    "entity_type": "NUMBER",
                                    "entity_name": f"{col_name}_数据量",
                                    "entity_value": str(len(values)),
                                    "context": f"Sheet: {sheet_name}"
                                }
                            ])
        
        else:
            # 非 Excel 文件使用分块处理
            if text_length > CHUNK_SIZE:
                chunks = [full_text[i:i+CHUNK_SIZE] for i in range(0, text_length, CHUNK_SIZE)]
                total_chunks = len(chunks)
                
                if progress_callback:
                    await progress_callback(f"文档较长，将分 {total_chunks} 块处理", f"{base_progress + 15}%")
                
                for idx, chunk in enumerate(chunks):
                    try:
                        if progress_callback:
                            await progress_callback(
                                f"正在处理第 {idx + 1}/{total_chunks} 块 ({len(chunk):,} 字符)...",
                                f"{base_progress + int((idx / total_chunks) * progress_range * 0.8)}%"
                            )
                        
                        entities = await llm_service.extract_entities(chunk, entity_types)
                        all_entities.extend(entities)
                    except Exception as e:
                        logger.error("Chunk extraction error: %s", e)
                        continue
            else:
                if progress_callback:
                    await progress_callback("正在提取实体...", f"{base_progress + int(progress_range * 0.4)}%")
                
                entities = await llm_service.extract_entities(full_text, entity_types)
                all_entities.extend(entities)
        
        # 自定义字段提取
        if custom_fields:
            if progress_callback:
                await progress_callback("正在提取自定义字段...", f"{base_progress + int(progress_range * 0.85)}%")
            
            custom_entities = await self._extract_custom_fields(full_text[:CHUNK_SIZE], custom_fields)
            all_entities.extend(custom_entities)
        
        # 提取表格数据
        tables = parsed_data.get("tables", [])
        if tables:
            table_entities = self._extract_table_entities(tables)
            all_entities.extend(table_entities)
        
        # 去重 - 使用 (entity_type, entity_name, entity_value) 作为去重key
        unique_entities = []
        seen = set()
        for entity in all_entities:
            key = (
                entity.get("entity_type"),
                entity.get("entity_name"),
                entity.get("entity_value", "")
            )
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        if progress_callback:
            await progress_callback(f"处理完成，共提取 {len(unique_entities)} 个实体", f"{base_progress + progress_range}%")
        
        return {
            "entities": unique_entities,
            "tables": tables,
            "parsed_data": parsed_data
        }
    
    async def _extract_custom_fields(
        self,
        text: str,
        custom_fields: List[str]
    ) -> List[Dict[str, Any]]:
        prompt = f"""从文本中提取以下自定义字段的信息：

自定义字段：
{chr(10).join([f"- {field}" for field in custom_fields])}

文本内容：
{text[:50000]}

请返回JSON格式：
```json
[
    {{
        "entity_type": "CUSTOM",
        "entity_name": "字段名",
        "entity_value": "提取的值",
        "context": "原文上下文"
    }}
]
```

只返回JSON。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await llm_service.chat_completion(messages, temperature=0.3)
        
        import json
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        except:
            return []
    
    def _extract_table_entities(self, tables: List[List[List[str]]]) -> List[Dict[str, Any]]:
        entities = []
        for i, table in enumerate(tables):
            if not table:
                continue
            
            headers = table[0] if table else []
            for row in table[1:]:
                for j, cell in enumerate(row):
                    if cell and cell.strip():
                        header = headers[j] if j < len(headers) else f"Column_{j}"
                        entities.append({
                            "entity_type": "TABLE_DATA",
                            "entity_name": header,
                            "entity_value": cell,
                            "context": f"Table {i+1}, Row data"
                        })
        return entities
    
    async def save_to_mongodb(
        self,
        document_id: UUID,
        extraction_result: Dict[str, Any]
    ):
        collection = get_collection("extractions")
        await collection.update_one(
            {"document_id": str(document_id)},
            {
                "$set": {
                    "document_id": str(document_id),
                    "entities": extraction_result.get("entities", []),
                    "tables": extraction_result.get("tables", []),
                    "updated_at": asyncio.get_event_loop().time()
                }
            },
            upsert=True
        )


extraction_service = ExtractionService()
