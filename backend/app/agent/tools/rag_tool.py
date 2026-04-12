"""
RAG检索工具 - 从向量数据库检索相关文档片段

功能：
- 基于查询从Qdrant检索相关文档片段
- 支持限定文档ID列表
- 返回带相关性的结果
"""

from typing import Any, Dict

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.services.rag_service import rag_service


class RAGTool(BaseTool):
    """RAG检索工具

    从向量数据库(Qdrant)中检索与查询相关的文档片段。
    这是数据查找的第三优先级（PG > Neo4j > RAG）。
    """

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def description(self) -> str:
        return """从向量数据库中检索与查询相关的文档片段。

使用场景：
- 当需要从文档中查找特定信息时
- 当PG和Neo4j查询未找到完整数据时
- 当需要基于语义相似性查找相关内容时

特点：
- 基于向量相似性检索
- 返回最相关的文档片段
- 支持限定特定文档"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询，描述你想要查找的信息"
                },
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定搜索的文档ID列表(可选，不传则搜索所有文档)"
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量，默认5条"
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行RAG检索"""
        try:
            query = params.get("query", "")
            doc_ids = params.get("doc_ids", context.file_ids)
            top_k = params.get("top_k", 5)

            if not query:
                return ToolResult(
                    success=False,
                    error="查询不能为空"
                )

            # 调用RAG服务
            if doc_ids:
                # 使用支持 doc_ids 前置过滤的 search_for_field
                results = await rag_service.search_for_field(
                    query=query,
                    doc_ids=doc_ids,
                    top_k=top_k
                )
            else:
                results = await rag_service.search_relevant_documents(
                    query=query,
                    top_k=top_k
                )

            # 格式化结果（兼容两种搜索方法的返回格式）
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "doc_id": result.get("doc_id") or (result.get("metadata", {}) or {}).get("original_doc_id"),
                    "doc_name": result.get("doc_name"),
                    "content": result.get("content", "")[:500],
                    "score": result.get("score", 0) or result.get("rerank_score", 0),
                    "chunk_type": result.get("chunk_type", "text")
                })

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results_count": len(formatted_results),
                    "results": formatted_results
                },
                metadata={
                    "searched_doc_ids": doc_ids,
                    "top_k": top_k
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"RAG检索失败: {str(e)}"
            )
