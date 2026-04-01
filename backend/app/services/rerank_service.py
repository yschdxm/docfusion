import httpx
from typing import List, Dict, Any
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RerankService:
    """重排服务 - 使用模力方舟API"""
    
    def __init__(self):
        self.api_key = settings.GITEE_AI_API_KEY
        self.base_url = settings.GITEE_AI_BASE_URL
        self.model = settings.RERANK_MODEL
        # SSL验证：总开关 AND Gitee AI开关
        self.ssl_verify = settings.SSL_VERIFY and settings.SSL_VERIFY_GITEE_AI
        logger.info(f"RerankService初始化: model={self.model}, base_url={self.base_url}, ssl_verify={self.ssl_verify}")
    
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
