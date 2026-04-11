from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from typing import List, Dict, Any, Optional
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
        """初始化集合，创建 payload 索引。"""
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

        # 创建 payload 索引用于过滤
        for field_name in ["source_file", "chunk_type", "file_type", "original_doc_id"]:
            try:
                await self.client.create_payload_index(
                    collection_name=self.COLLECTION_NAME,
                    field_name=field_name,
                    field_schema="keyword",
                )
            except Exception:
                pass  # 索引可能已存在

    async def add_document(
        self,
        doc_id: str,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any] = None
    ):
        """添加文档向量。"""
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
        documents: List[Dict[str, Any]]
    ):
        """批量添加文档向量。"""
        await self.connect()

        points = [
            PointStruct(
                id=str(doc["doc_id"]),
                vector=doc["embedding"],
                payload={
                    "content": doc["content"],
                    **(doc.get("metadata", {}))
                }
            )
            for doc in documents
        ]

        await self.client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=points
        )

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_conditions: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """搜索相似文档，支持 source_file 列表过滤。"""
        await self.connect()
        await self.init_collection()

        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        query_filter = None
        if filter_conditions:
            conditions = []
            for key, value in filter_conditions.items():
                if isinstance(value, list):
                    # 列表值使用 MatchAny
                    conditions.append(
                        FieldCondition(
                            key=key,
                            match=MatchAny(any=value)
                        )
                    )
                else:
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
        """删除文档向量（包括所有分块）。"""
        await self.connect()

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        try:
            await self.client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=[str(doc_id)]
            )
        except Exception:
            pass

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
        """获取文档向量。"""
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
