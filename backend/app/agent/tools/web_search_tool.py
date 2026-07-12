"""
联网搜索工具 - 从公开互联网检索信息并提取网页摘要

设计目标：
- 不依赖额外付费搜索 API，使用 DuckDuckGo HTML 搜索作为基础检索入口
- 对检索结果页面做轻量正文提取，给 LLM 提供可引用的标题、链接和摘要
- 网络不可用或结果为空时返回可降级的错误信息，不影响其他文档功能
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from app.agent.base.tool import BaseTool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """联网搜索工具"""

    SEARCH_URL = "https://duckduckgo.com/html/"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return """联网搜索公开网页信息，并返回搜索结果、来源链接和网页摘要。

使用场景：
- 用户询问互联网上的实时或公开信息，例如学校官网教师介绍、机构新闻、公开资料等
- 本地文档/数据库/知识图谱没有相关信息时，需要从网络补充
- 需要尽量引用官方网站、权威网站的信息来源

重要要求：
- 如果用户明确询问学校、学院、教师、官网信息，应优先搜索官方网站页面
- 回答时应说明信息来源链接
- 不要编造搜索结果中没有的信息"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "联网搜索关键词，建议包含官网、学校/机构名称、人物/主题等关键字",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回搜索结果数量，默认5条，最多10条",
                },
                "fetch_pages": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否抓取搜索结果网页正文摘要，默认开启",
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行联网搜索"""
        if context.metadata.get("web_search_enabled") is False:
            return ToolResult(
                success=False,
                error="联网搜索已关闭。请开启联网搜索后再查询网络信息。",
            )

        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(success=False, error="搜索关键词不能为空")

        top_k = min(max(int(params.get("top_k", 5) or 5), 1), 10)
        fetch_pages = bool(params.get("fetch_pages", True))

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=8.0),
                follow_redirects=True,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as client:
                results = await self._search_duckduckgo(client, query, top_k)

                if fetch_pages and results:
                    await asyncio.gather(
                        *(self._enrich_result_with_page_summary(client, item) for item in results[:top_k]),
                        return_exceptions=True,
                    )

            if not results:
                return ToolResult(
                    success=True,
                    data={
                        "query": query,
                        "results_count": 0,
                        "results": [],
                        "message": "未搜索到相关网络结果，请尝试更具体的关键词。",
                    },
                    metadata={"web_search_enabled": True, "search_engine": "duckduckgo_html"},
                )

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results_count": len(results),
                    "results": results,
                },
                metadata={
                    "web_search_enabled": True,
                    "search_engine": "duckduckgo_html",
                    "top_k": top_k,
                    "fetch_pages": fetch_pages,
                },
            )

        except httpx.TimeoutException:
            return ToolResult(success=False, error="联网搜索超时，请稍后重试或关闭联网搜索。")
        except Exception as e:
            logger.exception("[WebSearchTool] 联网搜索失败: %s", e)
            return ToolResult(success=False, error=f"联网搜索失败: {str(e)}")

    async def _search_duckduckgo(
        self,
        client: httpx.AsyncClient,
        query: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """使用 DuckDuckGo HTML 页面搜索"""
        # 对高校教师类问题加强官网倾向，但保留用户原问题
        search_query = query
        if any(keyword in query for keyword in ("学校", "大学", "学院", "老师", "教师", "教授")) and "官网" not in query:
            search_query = f"{query} 官网"

        resp = await client.get(self.SEARCH_URL, params={"q": search_query})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        nodes = soup.select(".result")
        results: List[Dict[str, Any]] = []

        for node in nodes:
            title_node = node.select_one(".result__title a") or node.select_one("a.result__a")
            snippet_node = node.select_one(".result__snippet")
            if not title_node:
                continue

            title = self._clean_text(title_node.get_text(" ", strip=True))
            href = title_node.get("href", "")
            url = self._normalize_duckduckgo_url(href)
            snippet = self._clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")

            if not title or not url or url.startswith("/"):
                continue

            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source_domain": urlparse(url).netloc,
                }
            )
            if len(results) >= top_k:
                break

        return results

    async def _enrich_result_with_page_summary(
        self,
        client: httpx.AsyncClient,
        result: Dict[str, Any],
    ) -> None:
        """抓取结果页面并提取正文摘要，失败时静默保留搜索摘要"""
        url = result.get("url")
        if not url:
            return

        try:
            resp = await client.get(url)
            content_type = resp.headers.get("content-type", "")
            if resp.status_code >= 400 or "text/html" not in content_type:
                return

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
                tag.decompose()

            title = self._clean_text((soup.title.string if soup.title else "") or "")
            meta_desc = ""
            meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
            if meta and meta.get("content"):
                meta_desc = self._clean_text(str(meta.get("content")))

            main_node = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", class_=re.compile("(content|main|article|detail|body)", re.I))
                or soup.body
            )
            text = self._clean_text(main_node.get_text(" ", strip=True) if main_node else "")
            summary_parts = [part for part in (meta_desc, text) if part]
            page_summary = self._truncate(" ".join(summary_parts), 900)

            if title and title != result.get("title"):
                result["page_title"] = title
            if page_summary:
                result["page_summary"] = page_summary

        except Exception as e:
            logger.debug("[WebSearchTool] 页面摘要抓取失败 | url=%s | error=%s", url, e)

    @staticmethod
    def _normalize_duckduckgo_url(href: str) -> str:
        """解析 DuckDuckGo 跳转链接中的真实 URL"""
        if not href:
            return ""

        if href.startswith("//"):
            href = "https:" + href

        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])

        return href

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len].rstrip() + "..."