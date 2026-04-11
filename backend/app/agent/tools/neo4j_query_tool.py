"""
Neo4j知识图谱查询工具 - 从图谱中查询实体和关系

功能：
- 自然语言转Cypher查询
- 查询知识图谱中的实体和关系
- 这是数据查找的第二优先级
"""

from typing import Any, Dict

from app.agent.base.tool import BaseTool, ToolContext, ToolResult

# 延迟导入，避免循环依赖
neo4j_query_service = None

def get_neo4j_query_service():
    global neo4j_query_service
    if neo4j_query_service is None:
        from app.services.neo4j_query_service import neo4j_query_service as service
        neo4j_query_service = service
    return neo4j_query_service


class Neo4jQueryTool(BaseTool):
    """Neo4j知识图谱查询工具

    从Neo4j知识图谱中查询实体和关系。
    这是数据查找的第二优先级（PG > Neo4j > RAG）。

    使用LLM将自然语言查询转换为Cypher并执行。
    """

    @property
    def name(self) -> str:
        return "query_knowledge_graph"

    @property
    def description(self) -> str:
        return """从Neo4j知识图谱中查询实体和关系。这是数据查找的第二优先级。

使用场景：
- 查找实体之间的关系
- 需要关联多个实体的复杂查询
- PG查询未找到完整数据时的补充查询

使用时机（重要）：
- 只有在PostgreSQL (query_pg_database) 查询尝试优化后仍无结果时才使用此工具
- 不要作为第一优先级直接使用

重要参数说明：
- doc_ids (可选): 限定查询的文档ID列表。如果提供，只查询这些文档中的实体；
  如果不提供，工具将返回错误，提示需要指定查询范围。
- query (必需): 自然语言查询描述

特点：
- 这是数据查找的第二优先级（PG > Neo4j > RAG）
- 支持自然语言查询，自动转换为Cypher
- 只能查询，不能修改数据
- 支持实体属性查询

数据查找优先级（必须遵循）：
1. PostgreSQL (query_pg_database) - 结构化数据，必须优先使用并尝试优化
2. Neo4j知识图谱 (此工具) - 实体关系数据，PG无结果时使用
3. RAG向量检索 - 非结构化文本
4. 原始文档 - 最后手段"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "自然语言查询描述，例如：'查找所有城市及其GDP'"
                },
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定查询的文档ID列表(可选)"
                },
                "max_results": {
                    "type": "integer",
                    "default": 50,
                    "description": "最大返回结果数，默认50"
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行Neo4j查询"""
        try:
            query = params.get("query", "")
            doc_ids = params.get("doc_ids", context.file_ids)
            max_results = params.get("max_results", 50)

            if not query:
                return ToolResult(
                    success=False,
                    error="查询描述不能为空"
                )

            # 使用Neo4j查询服务生成并执行Cypher
            all_records = []
            errors = []

            service = get_neo4j_query_service()

            if doc_ids:
                for doc_id in doc_ids:
                    try:
                        result = await service.generate_and_execute_once(
                            question=query,
                            table_headers=[],  # 暂时为空，让LLM自动推断
                            doc_ids=[doc_id]
                        )

                        if result.get("error") is None:
                            records = result.get("records", [])
                            all_records.extend(records)
                        else:
                            errors.append(f"Doc {doc_id}: {result.get('error', '未知错误')}")
                    except Exception as e:
                        errors.append(f"Doc {doc_id}: {str(e)}")
            else:
                # 尝试通用查询
                try:
                    result = await service.generate_and_execute_once(
                        question=query,
                        table_headers=[],
                        doc_ids=[]
                    )
                    if result.get("error") is None:
                        all_records = result.get("records", [])
                except Exception as e:
                    errors.append(str(e))

            # 去重
            seen = set()
            unique_records = []
            for record in all_records:
                key = str(record)
                if key not in seen:
                    seen.add(key)
                    unique_records.append(record)

            # 限制结果数
            unique_records = unique_records[:max_results]

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "records_count": len(unique_records),
                    "records": unique_records
                },
                metadata={
                    "queried_doc_ids": doc_ids,
                    "errors": errors if errors else None
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Neo4j查询失败: {str(e)}"
            )
