import httpx
from typing import List, Union
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingService:
    """嵌入服务 - 支持OpenAI兼容的嵌入API"""

    def __init__(self):
        self.api_key = ""
        self.base_url = ""
        self.model = ""
        self.ssl_verify = settings.SSL_VERIFY
        self._configured = False
        logger.info("EmbeddingService初始化: 等待数据库配置")

    async def apply_db_config(self, db) -> bool:
        """从数据库应用配置"""
        from app.services.config_service import config_service

        self.api_key = await config_service.get(db, "embedding_api_key", "")
        self.base_url = await config_service.get(db, "embedding_base_url", "")
        self.model = await config_service.get(db, "embedding_model", "")

        if not self.api_key or not self.base_url or not self.model:
            logger.warning("嵌入服务配置不完整，请在管理中心配置")
            return False

        self._configured = True
        logger.info(f"EmbeddingService配置已应用: model={self.model}, base_url={self.base_url}")
        return True
    
    async def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        将文本转换为向量

        Args:
            texts: 单个文本或文本列表

        Returns:
            向量列表
        """
        if not self._configured:
            raise RuntimeError("嵌入服务未配置，请在管理中心配置嵌入模型")

        if isinstance(texts, str):
            texts = [texts]

        logger.info(f"调用嵌入API: model={self.model}, texts_count={len(texts)}")
        
        async with httpx.AsyncClient(verify=self.ssl_verify) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "input": texts,
                    "encoding_format": "float"
                },
                timeout=120.0
            )
            response.raise_for_status()
            result = response.json()
            
            # 按index排序并提取向量
            embeddings = [item["embedding"] for item in sorted(result["data"], key=lambda x: x["index"])]
            logger.info(f"嵌入API返回: embeddings_count={len(embeddings)}, vector_dim={len(embeddings[0]) if embeddings else 0}")
            return embeddings
    
    async def embed_single(self, text: str) -> List[float]:
        """
        将单个文本转换为向量
        
        Args:
            text: 输入文本
            
        Returns:
            向量
        """
        embeddings = await self.embed(text)
        return embeddings[0]


embedding_service = EmbeddingService()
