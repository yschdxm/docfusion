import httpx
from typing import List, Union
import logging
import asyncio
import random
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingService:
    """嵌入服务 - 使用模力方舟API"""
    
    def __init__(self):
        self.api_key = settings.GITEE_AI_API_KEY
        self.base_url = settings.GITEE_AI_BASE_URL
        self.model = settings.EMBEDDING_MODEL
        # SSL验证：总开关 AND Gitee AI开关
        self.ssl_verify = settings.SSL_VERIFY and settings.SSL_VERIFY_GITEE_AI
        logger.info(f"EmbeddingService初始化: model={self.model}, base_url={self.base_url}, ssl_verify={self.ssl_verify}")
    
    async def _embed_with_retry(self, client: httpx.AsyncClient, texts: List[str]) -> dict:
        """调用嵌入API，带指数退避重试"""
        max_retries = settings.EMBEDDING_RETRY_MAX
        initial_delay = settings.EMBEDDING_RETRY_INITIAL_DELAY
        max_delay = settings.EMBEDDING_RETRY_MAX_DELAY

        for attempt in range(max_retries + 1):
            try:
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
                return response.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in (429,) or status >= 500:
                    if attempt < max_retries:
                        delay = min(initial_delay * (2 ** attempt), max_delay)
                        jitter = random.uniform(0, 0.5)
                        total_delay = delay + jitter
                        logger.warning(
                            f"嵌入API返回{status}，第{attempt+1}次重试，等待{total_delay:.1f}s"
                        )
                        await asyncio.sleep(total_delay)
                    else:
                        logger.error(f"嵌入API重试{max_retries}次后仍然失败: {status}")
                        raise
                else:
                    raise

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

        logger.info(f"调用嵌入API: model={self.model}, texts_count={len(texts)}")

        async with httpx.AsyncClient(verify=self.ssl_verify) as client:
            result = await self._embed_with_retry(client, texts)

            # 按index排序并提取向量
            embeddings = [item["embedding"] for item in sorted(result["data"], key=lambda x: x["index"])]
            logger.info(f"嵌入API返回: embeddings_count={len(embeddings)}, vector_dim={len(embeddings[0]) if embeddings else 0}")
            return embeddings

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量嵌入文本，带限流保护

        Args:
            texts: 文本列表

        Returns:
            向量列表
        """
        batch_size = settings.EMBEDDING_BATCH_SIZE
        delay_seconds = settings.EMBEDDING_CALL_DELAY_MS / 1000.0
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = await self.embed(batch)
            all_embeddings.extend(embeddings)

            # 批次间添加延迟（最后一组不添加）
            if i + batch_size < len(texts):
                await asyncio.sleep(delay_seconds)

        return all_embeddings
    
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
