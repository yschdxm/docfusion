"""
查询工具 - 自然语言查询和数据聚合

功能：
- 统一自然语言查询，自动路由到 PG/Neo4j/RAG
- 数据聚合统计分析
"""

import logging
from typing import Any, Dict, List

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel

logger = logging.getLogger(__name__)


class NaturalLanguageQueryTool(BaseTool):
    """自然语言查询工具"""

    @property
    def name(self) -> str:
        return "natural_language_query"

    @property
    def description(self) -> str:
        return """统一自然语言查询，自动路由到最合适的数据源。

使用场景：
- 当不确定应该使用哪个数据源时
- 当需要使用自然语言描述查询需求时
- 当需要同时查询多个数据源时

数据源：
- pg: PostgreSQL数据库（结构化数据）
- neo4j: Neo4j知识图谱（实体关系）
- rag: RAG向量检索（非结构化文本）

注意事项：
- 此工具会自动分析查询意图，选择最合适的数��源
- 可以通过data_sources参数限定数据源范围
- 查询结果会自动合并和去重"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_QUERY

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 60000  # 60秒

    @property
    def cacheable(self) -> bool:
        return True

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "自然语言查询"
                },
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定文档范围（可选）"
                },
                "data_sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["pg", "neo4j", "rag"]},
                    "description": "数据源（可选，默认自动选择）"
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行自然语言查询"""
        try:
            query = params.get("query", "")
            file_ids = params.get("file_ids", [])
            data_sources = params.get("data_sources", [])

            if not query:
                return ToolResult(success=False, error="查询不能为空")

            # 如果没有指定数据源，自动分析查询意图
            if not data_sources:
                data_sources = await self._analyze_query_intent(query)

            results = {}
            errors = []

            # 执行查询
            for source in data_sources:
                try:
                    if source == "pg":
                        pg_result = await self._query_pg(query, file_ids, context)
                        if pg_result:
                            results["pg"] = pg_result
                    elif source == "neo4j":
                        neo4j_result = await self._query_neo4j(query, file_ids, context)
                        if neo4j_result:
                            results["neo4j"] = neo4j_result
                    elif source == "rag":
                        rag_result = await self._query_rag(query, file_ids, context)
                        if rag_result:
                            results["rag"] = rag_result
                except Exception as e:
                    errors.append(f"{source}: {str(e)}")

            return ToolResult(
                success=len(results) > 0,
                data={
                    "query": query,
                    "data_sources": data_sources,
                    "results": results,
                    "errors": errors if errors else None
                }
            )

        except Exception as e:
            logger.exception(f"自然语言查询失败: {e}")
            return ToolResult(success=False, error=f"自然语言查询失败: {str(e)}")

    async def _analyze_query_intent(self, query: str) -> List[str]:
        """分析查询意图，选择数据源"""
        # 简单的启发式规则
        query_lower = query.lower()
        sources = []

        # 如果查询包含结构化数据相关的关键词，使用PG
        if any(kw in query_lower for kw in ["数据", "统计", "排名", "表格", "数量", "总计"]):
            sources.append("pg")

        # 如果查询包含实体相关的关键词，使用Neo4j
        if any(kw in query_lower for kw in ["谁", "哪里", "关系", "实体", "属于", "包含"]):
            sources.append("neo4j")

        # 如果查询包含文本相关的关键词，使用RAG
        if any(kw in query_lower for kw in ["内容", "描述", "解释", "说明", "文档"]):
            sources.append("rag")

        # 如果没有匹配到，使用所有数据源
        if not sources:
            sources = ["pg", "neo4j", "rag"]

        return sources

    async def _query_pg(self, query: str, file_ids: List[str], context: ToolContext) -> Dict[str, Any]:
        """查询PostgreSQL"""
        try:
            from app.services.sql_query_service import sql_query_service

            result = await sql_query_service.execute_natural_language_query(
                query=query,
                doc_ids=file_ids if file_ids else None
            )

            return result
        except Exception as e:
            logger.error(f"PG查询失败: {e}")
            return None

    async def _query_neo4j(self, query: str, file_ids: List[str], context: ToolContext) -> Dict[str, Any]:
        """查询Neo4j"""
        try:
            from app.services.knowledge_graph_service import knowledge_graph_service

            result = await knowledge_graph_service.query(
                query=query,
                document_ids=file_ids if file_ids else None
            )

            return result
        except Exception as e:
            logger.error(f"Neo4j查询失败: {e}")
            return None

    async def _query_rag(self, query: str, file_ids: List[str], context: ToolContext) -> Dict[str, Any]:
        """查询RAG"""
        try:
            from app.services.rag_service import rag_service

            result = await rag_service.search(
                query=query,
                doc_ids=file_ids if file_ids else None,
                top_k=10
            )

            return {"results": result}
        except Exception as e:
            logger.error(f"RAG查询失败: {e}")
            return None


class AggregateDataTool(BaseTool):
    """数据聚合工具"""

    @property
    def name(self) -> str:
        return "aggregate_data"

    @property
    def description(self) -> str:
        return """对Excel数据进行聚合统计分析。

使用场景：
- 当需要对表格数据进行统计分析时
- 当需要计算总和、平均值、最大值、最小值等时
- 当需要按某个字段分组统计时

支持的聚合函数：
- sum: 求和
- avg: 平均值
- min: 最小值
- max: 最大值
- count: 计数

注意事项：
- 此工具仅支持xlsx文件
- group_by参数用于指定分组字段"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_QUERY

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 30000  # 30秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（可选）"
                },
                "aggregations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string", "description": "列名"},
                            "function": {
                                "type": "string",
                                "enum": ["sum", "avg", "min", "max", "count"],
                                "description": "聚合函数"
                            }
                        },
                        "required": ["column", "function"]
                    },
                    "description": "聚合配置"
                },
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "分组字段（可选）"
                }
            },
            "required": ["file_id", "aggregations"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行数据聚合"""
        try:
            file_id = params.get("file_id", "")
            sheet_name = params.get("sheet_name")
            aggregations = params.get("aggregations", [])
            group_by = params.get("group_by", [])

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if not aggregations:
                return ToolResult(success=False, error="聚合配置不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if doc.file_type != "xlsx":
                    return ToolResult(success=False, error=f"不支持的文件类型: {doc.file_type}，仅支持xlsx")

                # 使用pandas进行数据聚合
                try:
                    import pandas as pd

                    # 读取Excel
                    df = pd.read_excel(doc.file_path, sheet_name=sheet_name)

                    # 执行聚合
                    if group_by:
                        grouped = df.groupby(group_by)
                        results = {}
                        for agg in aggregations:
                            col = agg["column"]
                            func = agg["function"]
                            if col not in df.columns:
                                continue

                            if func == "sum":
                                results[f"{col}_sum"] = grouped[col].sum().to_dict()
                            elif func == "avg":
                                results[f"{col}_avg"] = grouped[col].mean().to_dict()
                            elif func == "min":
                                results[f"{col}_min"] = grouped[col].min().to_dict()
                            elif func == "max":
                                results[f"{col}_max"] = grouped[col].max().to_dict()
                            elif func == "count":
                                results[f"{col}_count"] = grouped[col].count().to_dict()
                    else:
                        results = {}
                        for agg in aggregations:
                            col = agg["column"]
                            func = agg["function"]
                            if col not in df.columns:
                                continue

                            if func == "sum":
                                results[f"{col}_sum"] = float(df[col].sum())
                            elif func == "avg":
                                results[f"{col}_avg"] = float(df[col].mean())
                            elif func == "min":
                                results[f"{col}_min"] = float(df[col].min())
                            elif func == "max":
                                results[f"{col}_max"] = float(df[col].max())
                            elif func == "count":
                                results[f"{col}_count"] = int(df[col].count())

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "sheet_name": sheet_name,
                            "group_by": group_by,
                            "results": results,
                            "total_rows": len(df)
                        }
                    )

                except ImportError:
                    return ToolResult(success=False, error="pandas未安装，无法执行数据聚合")
                except Exception as e:
                    return ToolResult(success=False, error=f"数据聚合失败: {str(e)}")

        except Exception as e:
            logger.exception(f"数据聚合失败: {e}")
            return ToolResult(success=False, error=f"数据聚合失败: {str(e)}")
