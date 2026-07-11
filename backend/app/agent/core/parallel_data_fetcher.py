"""
并行数据获取器 - 支持多数据源并行查询

负责：
- 并行执行多个数据查询
- 支持PostgreSQL、Neo4j、RAG
"""

from typing import Dict, Any, List
from dataclasses import dataclass
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class DataQuery:
    """数据查询"""
    source_type: str  # "postgresql", "neo4j", "rag"
    query: str
    params: Dict[str, Any]
    timeout_ms: int = 20000


class ParallelDataFetcher:
    """并行数据获取器

    支持多数据源并行查询。
    """

    async def fetch_all(self, queries: List[DataQuery]) -> List[Dict[str, Any]]:
        """并行获取所有数据

        Args:
            queries: 查询列表

        Returns:
            结果列表
        """
        logger.info(f"[ParallelDataFetcher] 并行执行 {len(queries)} 个查询")

        # 创建任务列表
        tasks = [self._fetch_single(query) for query in queries]

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[ParallelDataFetcher] 查询 {i} 失败: {result}")
                final_results.append({"error": str(result), "source": queries[i].source_type})
            else:
                final_results.append(result)

        return final_results

    async def _fetch_single(self, query: DataQuery) -> Dict[str, Any]:
        """执行单个查询

        Args:
            query: 数据查询

        Returns:
            查询结果
        """
        try:
            if query.source_type == "postgresql":
                return await self._fetch_pg(query)
            elif query.source_type == "neo4j":
                return await self._fetch_neo4j(query)
            elif query.source_type == "rag":
                return await self._fetch_rag(query)
            else:
                raise ValueError(f"未知的数据源类型: {query.source_type}")

        except asyncio.TimeoutError:
            logger.error(f"[ParallelDataFetcher] 查询超时: {query.source_type}")
            raise
        except Exception as e:
            logger.error(f"[ParallelDataFetcher] 查询失败: {query.source_type} - {e}")
            raise

    async def _fetch_pg(self, query: DataQuery) -> Dict[str, Any]:
        """查询PostgreSQL"""
        from app.services.sql_query_service import sql_query_service

        result = await asyncio.wait_for(
            sql_query_service.execute_query(query.query),
            timeout=query.timeout_ms / 1000
        )

        return {
            "source": "postgresql",
            "data": result.get("records", []),
            "columns": result.get("columns", []),
            "count": len(result.get("records", []))
        }

    async def _fetch_neo4j(self, query: DataQuery) -> Dict[str, Any]:
        """查询Neo4j"""
        from app.services.knowledge_graph_service import knowledge_graph_service

        result = await asyncio.wait_for(
            knowledge_graph_service.query(query.query),
            timeout=query.timeout_ms / 1000
        )

        return {
            "source": "neo4j",
            "data": result.get("results", []),
            "count": len(result.get("results", []))
        }

    async def _fetch_rag(self, query: DataQuery) -> Dict[str, Any]:
        """查询RAG"""
        from app.services.rag_service import rag_service

        result = await asyncio.wait_for(
            rag_service.search(query.query, query.params.get("top_k", 10)),
            timeout=query.timeout_ms / 1000
        )

        return {
            "source": "rag",
            "data": result,
            "count": len(result)
        }


# 全局并行数据获取器实例
parallel_data_fetcher = ParallelDataFetcher()
