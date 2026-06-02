import httpx
from typing import List, Dict, Any
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RerankService:
    """重排服务 - 支持OpenAI兼容的重排API"""

    def __init__(self):
        self.api_key = ""
        self.base_url = ""
        self.model = ""
        self.ssl_verify = settings.SSL_VERIFY
        self._configured = False
        logger.info("RerankService初始化: 等待数据库配置")

    async def apply_db_config(self, db) -> bool:
        """从数据库应用配置"""
        from app.services.config_service import config_service

        self.api_key = await config_service.get(db, "rerank_api_key", "")
        self.base_url = await config_service.get(db, "rerank_base_url", "")
        self.model = await config_service.get(db, "rerank_model", "")

        if not self.api_key or not self.base_url or not self.model:
            logger.warning("重排服务配置不完整，请在管理中心配置")
            return False

        self._configured = True
        logger.info(f"RerankService配置已应用: model={self.model}, base_url={self.base_url}")
        return True
    
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: int = None
    ) -> List[Dict[str, Any]]:
        """
        对文档进行重排序

        Args:
            query: 查询文本
            documents: 待排序的文档列表
            top_n: 返回前N个结果

        Returns:
            重排后的结果列表，包含index和relevance_score
        """
        if not self._configured:
            raise RuntimeError("重排服务未配置，请在管理中心配置重排模型")

        logger.info(f"调用重排API: model={self.model}, query_len={len(query)}, docs_count={len(documents)}, top_n={top_n}")
        
        async with httpx.AsyncClient(verify=self.ssl_verify) as client:
            response = await client.post(
                f"{self.base_url}/rerank",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n or len(documents)
                },
                timeout=120.0
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"重排API返回: results_count={len(result)}")
            return result
    
    async def rerank_and_get_documents(
        self,
        query: str,
        documents: List[str],
        top_n: int = 5
    ) -> List[str]:
        """
        重排序并返回文档内容
        
        Args:
            query: 查询文本
            documents: 待排序的文档列表
            top_n: 返回前N个结果
            
        Returns:
            按相关度排序的文档列表
        """
        results = await self.rerank(query, documents, top_n)
        
        # 按relevance_score降序排序
        sorted_results = sorted(results, key=lambda x: x["relevance_score"], reverse=True)
        
        # 返回对应的文档
        return [documents[r["index"]] for r in sorted_results[:top_n]]


rerank_service = RerankService()
