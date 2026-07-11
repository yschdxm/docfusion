"""
搜索工具 - 跨文档搜索和网络搜索

功能：
- 跨文档搜索，支持keyword/semantic/hybrid模式
- 网络搜索
"""

import logging
from typing import Any, Dict

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel

logger = logging.getLogger(__name__)


class SearchDocumentsTool(BaseTool):
    """跨文档搜索工具"""

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return """跨文档搜索，支持keyword/semantic/hybrid模式。

使用场景：
- 当需要在多个文档中搜索特定内容时
- 当需要使用语义搜索查找相关内容时
- 当需要结合关键词和语义搜索时

搜索模式：
- keyword: 关键词匹配，速度快，适合精确搜索
- semantic: 语义检索，适合模糊搜索和语义相关的内容
- hybrid: 结合两种方式，兼顾速度和准确性

注意事项：
- hybrid模式会同时使用关键词和语义搜索，可能需要更多时间
- file_types参数可以过滤特定类型的文档"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SEARCH

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
                "query": {
                    "type": "string",
                    "description": "搜索查询"
                },
                "mode": {
                    "type": "string",
                    "enum": ["keyword", "semantic", "hybrid"],
                    "default": "hybrid",
                    "description": "搜索模式"
                },
                "file_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "文件类型过滤（可选）"
                },
                "top_k": {
                    "type": "integer",
                    "default": 10,
                    "description": "返回结果数量"
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行跨文档搜索"""
        try:
            query = params.get("query", "")
            mode = params.get("mode", "hybrid")
            file_types = params.get("file_types", [])
            top_k = params.get("top_k", 10)

            if not query:
                return ToolResult(success=False, error="搜索查询不能为空")

            # 调用RAG服务执行搜索
            from app.services.rag_service import rag_service

            search_results = await rag_service.search(
                query=query,
                mode=mode,
                file_types=file_types if file_types else None,
                top_k=top_k,
                user_id=context.user_id
            )

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "mode": mode,
                    "results": search_results,
                    "total_count": len(search_results)
                }
            )

        except Exception as e:
            logger.exception(f"跨文档搜索失败: {e}")
            return ToolResult(success=False, error=f"跨文档搜索失败: {str(e)}")


class WebSearchTool(BaseTool):
    """网络搜索工具"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return """在互联网上搜索信息。

使用场景：
- 当需要获取最新的信息时
- 当需要查找文档中没有的内容时
- 当需要验证某些信息时

注意事项：
- 网络搜索需要外部API支持
- 搜索结果可能需要进一步验证"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SEARCH

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 15000  # 15秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询"
                },
                "num_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量"
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行网络搜索"""
        try:
            query = params.get("query", "")
            num_results = params.get("num_results", 5)

            if not query:
                return ToolResult(success=False, error="搜索查询不能为空")

            # 调用网络搜索服务
            # 这里需要根据实际的搜索API实现
            # 示例实现：
            try:
                import httpx

                # 使用配置的搜索API
                from app.core.config import get_settings
                settings = get_settings()

                # 这里应该调用实际的搜索API（如Bing、Google等）
                # 示例：使用Bing搜索API
                # api_key = settings.BING_API_KEY
                # endpoint = "https://api.bing.microsoft.com/v7.0/search"
                # headers = {"Ocp-Apim-Subscription-Key": api_key}
                # params = {"q": query, "count": num_results}
                # async with httpx.AsyncClient() as client:
                #     response = await client.get(endpoint, headers=headers, params=params)
                #     results = response.json()

                # 暂时返回模拟结果
                results = {
                    "webPages": {
                        "value": [
                            {
                                "name": f"搜索结果 {i+1}",
                                "url": f"https://example.com/result{i+1}",
                                "snippet": f"这是关于'{query}'的搜索结果 {i+1}"
                            }
                            for i in range(num_results)
                        ]
                    }
                }

                # 格式化结果
                formatted_results = []
                for item in results.get("webPages", {}).get("value", []):
                    formatted_results.append({
                        "title": item.get("name", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", "")
                    })

                return ToolResult(
                    success=True,
                    data={
                        "query": query,
                        "results": formatted_results,
                        "total_count": len(formatted_results)
                    }
                )

            except ImportError:
                return ToolResult(
                    success=False,
                    error="httpx未安装，无法执行网络搜索"
                )
            except Exception as e:
                logger.error(f"网络搜索API调用失败: {e}")
                return ToolResult(
                    success=False,
                    error=f"网络搜索失败: {str(e)}"
                )

        except Exception as e:
            logger.exception(f"网络搜索失败: {e}")
            return ToolResult(success=False, error=f"网络搜索失败: {str(e)}")
