import httpx
from typing import List, Union
from app.core.config import get_settings

settings = get_settings()


class EmbeddingService:
    """嵌入服务 - 使用模力方舟API"""
    
    def __init__(self):
        self.api_key = settings.GITEE_AI_API_KEY
        self.base_url = settings.GITEE_AI_BASE_URL
        self.model = settings.EMBEDDING_MODEL
    
    async def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        将文本转换为向量
        
        Args:
            texts: 单个文本或文本列表
            
        Returns:
            向量列表
        """
        if isinstance(texts, str):
            texts = [texts]
        
        async with httpx.AsyncClient() as client:
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
                timeout=60.0
            )
            response.raise_for_status()
            result = response.json()
            
            # 按index排序并提取向量
            embeddings = [item["embedding"] for item in sorted(result["data"], key=lambda x: x["index"])]
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
