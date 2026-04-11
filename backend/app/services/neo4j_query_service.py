"""Neo4j 查询服务 — 让LLM生成Cypher查询并执行"""
import logging
from typing import List, Dict, Any
from app.services.llm_service import llm_service
from app.db.neo4j_db import run_cypher
from app.services.prompts.neo4j_prompt import NEO4J_QUERY_PROMPT, NEO4J_RETRY_PROMPT, NEO4J_EXTRACT_PROMPT

logger = logging.getLogger(__name__)


class Neo4jQueryService:

    async def _get_neo4j_schema(self, doc_ids: List[str]) -> str:
        """获取Neo4j数据库的schema信息，供LLM参考。"""
        try:
            # 查询有哪些节点类型（Label）
            labels_result = await run_cypher(
                """
                CALL db.labels() YIELD label
                RETURN collect(label) as labels
                """,
                {}
            )
            labels = labels_result[0]["labels"] if labels_result else []

            # 查询有哪些关系类型
            rel_types_result = await run_cypher(
                """
                CALL db.relationshipTypes() YIELD relationshipType
                RETURN collect(relationshipType) as types
                """,
                {}
            )
            rel_types = rel_types_result[0]["types"] if rel_types_result else []

            # 查询节点样本（每种类型的前2个）
            sample_nodes = []
            # 根据 doc_ids 动态构建过滤条件
            query_filter = ""
            params = {}
            if doc_ids:
                query_filter = "WHERE any(did IN $doc_ids WHERE did IN n.document_ids)"
                params = {"doc_ids": doc_ids}

            if labels:
                for label in labels[:5]:  # 只取前5种类型避免查询过多
                    try:
                        nodes_result = await run_cypher(
                            f"""
                            MATCH (n:{label})
                            {query_filter}
                            RETURN n.name as name, keys(n) as prop_keys, labels(n) as labels
                            LIMIT 2
                            """,
                            params
                        )
                        if nodes_result:
                            sample_nodes.extend(nodes_result)
                    except Exception:
                        pass

            # 构建schema描述
            schema_lines = ["节点类型（Labels）:", ", ".join(labels[:20])]
            if rel_types:
                schema_lines.extend(["", "关系类型:", ", ".join(rel_types[:20])])

            if sample_nodes:
                schema_lines.extend(["", "节点样本（属性是平铺存储的，不是JSON）:"])
                for node in sample_nodes[:5]:
                    name = node.get("name", "N/A")
                    prop_keys = node.get("prop_keys", [])
                    label = node.get("labels", ["Unknown"])[0]
                    # 过滤掉document_ids，显示其他属性
                    other_props = [k for k in prop_keys if k not in ["document_ids", "name"]][:5]
                    props_str = ", ".join(other_props) if other_props else "无其他属性"
                    schema_lines.append(f"  - {label}: {name} (属性: {props_str})")

            return "\n".join(schema_lines)
        except Exception as e:
            logger.warning("[NEO4J-SCHEMA] 获取schema失败: %s", e)
            return "无法获取schema信息"

    async def _convert_to_records(
        self,
        results: List[Dict[str, Any]],
        table_headers: List[str],
    ) -> List[Dict[str, Any]]:
        """将Neo4j查询结果转换为结构化记录。"""
        if not results:
            return []

        headers_str = "，".join([h for h in table_headers if h]) if table_headers else ""

        # 准备结果文本
        results_text = []
        for i, r in enumerate(results[:20]):  # 最多20条用于提取
            results_text.append(f"记录{i+1}: {r}")

        prompt = NEO4J_EXTRACT_PROMPT.format(
            table_headers=headers_str,
            results="\n".join(results_text),
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            response = await llm_service.chat_completion(messages, temperature=0.3, max_tokens=65536, enable_thinking=False)
            result = llm_service._extract_json(response)
            records = result.get("records", [])
            return records
        except Exception as e:
            logger.warning("[NEO4J-EXTRACT] 提取记录失败: %s", e)
            return []

    async def generate_and_execute_once(
        self,
        question: str,
        table_headers: List[str],
        doc_ids: List[str],
        document_title: str = "",
        previous_error: str = "",
    ) -> Dict[str, Any]:
        """单次生成Cypher并执行，不重试。用于外层控制重试逻辑。

        Returns:
            {"cypher": str, "records": List[Dict], "error": str|None}
        """
        if not doc_ids:
            return {"cypher": "", "records": [], "error": "没有提供doc_ids参数。请在查询时指定doc_ids参数，限定查询的文档范围。例如：doc_ids=['doc_id_1', 'doc_id_2']"}

        schema = await self._get_neo4j_schema(doc_ids)
        headers_str = "，".join([h for h in table_headers if h]) if table_headers else "相关字段"

        messages = [
            {"role": "system", "content": f"你是Neo4j Cypher查询专家。生成高效、准确的Cypher查询语句。\n\n## 文档标题（数据范围约束）\n{document_title if document_title else '未指定'}\n\n根据文档标题，只查询与该主题相关的数据。"},
        ]

        if previous_error:
            prompt = NEO4J_RETRY_PROMPT.format(
                cypher="",
                error_or_empty_reason=previous_error,
                schema=schema,
                doc_ids=doc_ids,
            )
        else:
            prompt = NEO4J_QUERY_PROMPT.format(
                question=question,
                table_headers=headers_str,
                schema=schema,
                doc_ids=doc_ids,
                document_title=document_title if document_title else "未指定",
            )
        logger.debug("[NEO4J-QUERY-ONCE] prompt: %s", prompt)

        messages.append({"role": "user", "content": prompt})

        try:
            response = await llm_service.chat_completion(messages, temperature=0.3, max_tokens=65536, enable_thinking=False)
            result = llm_service._extract_json(response)
            cypher = result.get("cypher", "")
            explanation = result.get("explanation", "")

            if not cypher:
                return {"cypher": "", "records": [], "error": "未生成有效的Cypher查询"}

            # 安全检查
            cypher_upper = cypher.upper().strip()
            forbidden = ["CREATE", "DELETE", "REMOVE", "SET", "MERGE", "DROP", "ALTER"]
            if any(f in cypher_upper for f in forbidden):
                return {"cypher": cypher, "records": [], "error": "查询包含危险操作（CREATE/DELETE/MERGE等）"}

            # 执行查询
            results = await run_cypher(cypher, {"doc_ids": doc_ids})

            if not results:
                return {"cypher": cypher, "records": [], "error": "查询返回空结果"}

            # 转换为记录
            records = await self._convert_to_records(results, table_headers)
            return {"cypher": cypher, "records": records, "error": None, "explanation": explanation}

        except Exception as e:
            return {"cypher": "", "records": [], "error": str(e)}


neo4j_query_service = Neo4jQueryService()
