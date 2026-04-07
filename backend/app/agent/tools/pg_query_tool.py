"""
PostgreSQL查询工具 - 查询结构化数据

功能：
- 自然语言转SQL
- 查询PG数据库中的xlsx数据
- 这是数据查找的第一优先级
"""

import logging
from typing import Any, Dict, List

from app.agent.base.tool import BaseTool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# 延迟导入，避免循环依赖
sql_query_service = None
document_model = None

def get_sql_query_service():
    global sql_query_service
    if sql_query_service is None:
        from app.services.sql_query_service import sql_query_service as service
        sql_query_service = service
    return sql_query_service


def get_document_model():
    """获取Document模型类"""
    global document_model
    if document_model is None:
        from app.models.document import Document
        document_model = Document
    return document_model


async def get_doc_file_types(doc_ids: List[str]) -> Dict[str, str]:
    """查询文档的文件类型

    Returns:
        Dict[str, str]: {doc_id: file_type}
    """
    result = {}
    try:
        Document = get_document_model()
        from app.db.postgres import async_session
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import UUID

        async with async_session() as session:
            stmt = select(Document.id, Document.file_type).where(
                Document.id.in_([UUID(did) if isinstance(did, str) else did for did in doc_ids])
            )
            rows = await session.execute(stmt)
            for row in rows:
                result[str(row.id)] = row.file_type
    except Exception as e:
        logger.warning(f"[PGQueryTool] 查询文档类型失败: {e}")
    return result


class PGQueryTool(BaseTool):
    """PostgreSQL查询工具

    从PostgreSQL数据库中查询结构化数据。
    这是数据查找的第一优先级，因为xlsx数据在预处理时已入库。

    使用LLM将自然语言查询转换为SQL并执行。
    """

    @property
    def name(self) -> str:
        return "query_pg_database"

    @property
    def description(self) -> str:
        return """查询PostgreSQL数据库中的结构化数据。

使用场景：
- 查找xlsx文件中的结构化数据（只有xlsx数据在PG中）
- 需要精确匹配的数据查询
- 需要聚合统计的查询

重要提醒（关于文档类型）：
- xlsx文档：数据在PG中，优先使用此工具查询
- docx/md/txt文档：PG中**没有数据**，这些文档的数据在Neo4j知识图谱中，应该直接使用 query_knowledge_graph
- 如果传入的doc_ids包含非xlsx文档，本工具会返回提示建议使用Neo4j

特点：
- 支持自然语言查询，自动转换为SQL
- 只能查询，不能修改数据
- 支持中文列名

查询失败时的处理策略：
1. 如果返回结果很少或为空，首先分析原因：
   - 查询条件是否过于严格
   - 列名是否正确匹配
   - 是否需要更宽泛的匹配条件
2. 优化查询后再次调用本工具重试
3. 只有在多次优化尝试后仍无结果，才考虑使用其他数据源

数据查找策略（根据文档类型选择）：
- xlsx文件：PG (此工具) → Neo4j → RAG → 原始文档
- docx/md/txt文件：Neo4j (query_knowledge_graph) → RAG → 原始文档

注意：对于docx/md/txt文档，不要在此工具上浪费多次重试，应该直接使用Neo4j查询"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "自然语言查询描述，例如：'查询所有城市的GDP数据'"
                },
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定查询的文档ID列表(可选，不传则查询所有表)"
                },
                "max_rows": {
                    "type": "integer",
                    "default": 100,
                    "description": "最大返回行数，默认100"
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行PG查询（带重试机制）"""
        try:
            query = params.get("query", "")
            doc_ids = params.get("doc_ids", context.file_ids)
            max_rows = params.get("max_rows", 200)

            if not query:
                return ToolResult(
                    success=False,
                    error="查询描述不能为空"
                )

            if not doc_ids:
                return ToolResult(
                    success=False,
                    error="需要指定文档ID才能查询"
                )

            # 检查文档类型
            doc_types = await get_doc_file_types(doc_ids)
            non_xlsx_docs = [doc_id for doc_id, file_type in doc_types.items() if file_type != "xlsx"]
            xlsx_docs = [doc_id for doc_id, file_type in doc_types.items() if file_type == "xlsx"]

            # 如果所有文档都是非xlsx类型，直接提示使用Neo4j
            if non_xlsx_docs and not xlsx_docs:
                doc_types_str = ", ".join([f"{doc_id}({doc_types.get(doc_id, 'unknown')})" for doc_id in doc_ids])
                return ToolResult(
                    success=True,
                    data={
                        "query": query,
                        "records_count": 0,
                        "records": [],
                        "columns": [],
                        "suggestion": f"当前查询的文档类型为 {doc_types_str}。非xlsx文档(docx/md/txt)的数据不在PostgreSQL中，而是在Neo4j知识图谱里。请直接使用 query_knowledge_graph 工具查询。"
                    },
                    metadata={
                        "doc_types": doc_types,
                        "recommendation": "use_neo4j"
                    }
                )

            # 如果有混合类型，只查询xlsx文档，同时提示
            if non_xlsx_docs and xlsx_docs:
                logger.info(f"[PGQueryTool] 混合文档类型，只查询xlsx: {xlsx_docs}, 跳过: {non_xlsx_docs}")
                doc_ids = xlsx_docs

            service = get_sql_query_service()

            # 使用新的重试机制查询所有文档
            all_records = []
            all_sqls = []

            for doc_id in doc_ids:
                try:
                    result = await service.generate_and_execute(
                        question=query,
                        doc_ids=[doc_id],
                        max_retries=3
                    )

                    if result.get("error") is None:
                        records = result.get("records", [])
                        all_records.extend(records)
                        all_sqls.append(result.get("sql", ""))
                except Exception as e:
                    logger.warning(f"[PGQueryTool] 查询doc {doc_id} 失败: {e}")

            # 去重
            seen = set()
            unique_records = []
            for record in all_records:
                key = tuple(sorted([(k, str(v)) for k, v in record.items()]))
                if key not in seen:
                    seen.add(key)
                    unique_records.append(record)

            # 限制行数
            unique_records = unique_records[:max_rows]

            # 如果结果为空，给出友好提示和优化建议
            if not unique_records:
                return ToolResult(
                    success=True,  # 查询本身成功，只是没数据
                    data={
                        "query": query,
                        "records_count": 0,
                        "records": [],
                        "columns": [],
                        "suggestion": "未找到匹配数据。建议优化策略: 1) 使用更宽泛的关键词 2) 尝试LIKE模糊匹配 3) 检查列名是否正确 4) 使用不同表述重试查询"
                    },
                    metadata={
                        "queried_doc_ids": doc_ids,
                        "sql_samples": all_sqls[:3] if all_sqls else []
                    }
                )

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "records_count": len(unique_records),
                    "records": unique_records,
                    "columns": list(unique_records[0].keys()) if unique_records else []
                },
                metadata={
                    "queried_doc_ids": doc_ids,
                    "total_fetched": len(all_records),
                    "sql_samples": all_sqls[:3] if all_sqls else []
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"PG查询失败: {str(e)}"
            )
