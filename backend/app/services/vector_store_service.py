from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class VectorStoreService:
    """向量存储服务 - 使用Qdrant"""
    
    COLLECTION_NAME = "documents"
    
    def __init__(self):
        self.client: Optional[AsyncQdrantClient] = None
    
    async def connect(self):
        """连接到Qdrant"""
        if self.client is None:
            self.client = AsyncQdrantClient(url=settings.QDRANT_URL)
    
    async def init_collection(self, vector_size: int = 1024):
        """
        初始化集合
        
        Args:
            vector_size: 向量维度 (bge-m3默认1024维)
        """
        await self.connect()
        
        collections = await self.client.get_collections()
        collection_names = [c.name for c in collections.collections]
        
        if self.COLLECTION_NAME not in collection_names:
            await self.client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )
    
    async def add_document(
        self,
        doc_id: str,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any] = None
    ):
        """
        添加文档向量
        
        Args:
            doc_id: 文档ID
            content: 文档内容
            embedding: 向量
            metadata: 元数据
        """
        await self.connect()
        
        point = PointStruct(
            id=str(doc_id),
            vector=embedding,
            payload={
                "content": content,
                **(metadata or {})
            }
        )
        
        await self.client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[point]
        )
    
    async def add_documents(
        self,
        documents: List[Dict[str, Any]],
        batch_size: int = 100
    ):
        """
        批量添加文档向量（支持分批插入避免超时）

        Args:
            documents: 文档列表，每个包含doc_id, content, embedding, metadata
            batch_size: 每批插入的文档数量
        """
        import asyncio
        await self.connect()

        total_docs = len(documents)
        logger.info(f"开始批量插入文档向量，共 {total_docs} 个文档，每批 {batch_size} 个")

        for i in range(0, total_docs, batch_size):
            batch = documents[i:i + batch_size]

            points = [
                PointStruct(
                    id=str(doc["doc_id"]),
                    vector=doc["embedding"],
                    payload={
                        "content": doc["content"],
                        **(doc.get("metadata", {}))
                    }
                )
                for doc in batch
            ]

            try:
                await self.client.upsert(
                    collection_name=self.COLLECTION_NAME,
                    points=points
                )
                logger.info(f"已插入第 {i + len(batch)}/{total_docs} 个文档")
            except Exception as e:
                logger.error(f"插入批次失败 (第 {i}-{i + len(batch)} 个): {e}")
                raise

            # 批次间添加短暂延迟（最后一组不添加）
            if i + batch_size < total_docs:
                await asyncio.sleep(0.1)
    
    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_conditions: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索相似文档
        
        Args:
            query_vector: 查询向量
            top_k: 返回数量
            filter_conditions: 过滤条件
            
        Returns:
            相似文档列表
        """
        await self.connect()
        
        # 确保集合存在
        await self.init_collection()
        
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        query_filter = None
        if filter_conditions:
            conditions = []
            for key, value in filter_conditions.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            query_filter = Filter(must=conditions)
        
        results = await self.client.search(
            collection_name=self.COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter
        )
        
        return [
            {
                "doc_id": hit.id,
                "score": hit.score,
                "content": hit.payload.get("content", ""),
                "metadata": {k: v for k, v in hit.payload.items() if k != "content"}
            }
            for hit in results
        ]
    
    async def delete_document(self, doc_id: str):
        """
        删除文档向量（包括所有分块）
        
        Args:
            doc_id: 文档ID
        """
        await self.connect()
        
        # 删除所有以 doc_id 开头的块（格式：doc_id_chunk_0, doc_id_chunk_1, ...）
        # 使用 filter 删除
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        try:
            # 先尝试删除直接匹配的ID
            await self.client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=[str(doc_id)]
            )
        except Exception:
            pass
        
        # 删除所有相关的块
        try:
            await self.client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="original_doc_id",
                            match=MatchValue(value=str(doc_id))
                        )
                    ]
                )
            )
        except Exception as e:
            logger.warning(f"删除文档块失败: {e}")
    
    async def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        获取文档向量
        
        Args:
            doc_id: 文档ID
            
        Returns:
            文档信息
        """
        await self.connect()
        
        results = await self.client.retrieve(
            collection_name=self.COLLECTION_NAME,
            ids=[str(doc_id)]
        )
        
        if results:
            hit = results[0]
            return {
                "doc_id": hit.id,
                "content": hit.payload.get("content", ""),
                "metadata": {k: v for k, v in hit.payload.items() if k != "content"}
            }
        return None


vector_store_service = VectorStoreService()
