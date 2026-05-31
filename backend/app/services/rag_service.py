from typing import List, Dict, Any
import asyncio
import logging
from app.services.embedding_service import embedding_service
from app.services.rerank_service import rerank_service
from app.services.vector_store_service import vector_store_service
from app.db.neo4j_db import run_cypher

logger = logging.getLogger(__name__)


class RAGService:
    """RAG服务 - 检索增强生成"""

    # 分块参数
    CHUNK_SIZE = 2500  # 每块2500字（适配 bge-m3 的 8192 token 上下文）
    CHUNK_OVERLAP = 200  # 重叠200字
    MIN_CHUNK_SIZE = 200  # 最小块大小

    async def init(self):
        """初始化向量存储"""
        await vector_store_service.init_collection()

    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[Dict[str, Any]]:
        """将文本分成多个块。"""
        chunk_size = chunk_size or self.CHUNK_SIZE
        overlap = overlap or self.CHUNK_OVERLAP

        if len(text) <= chunk_size:
            return [{"chunk_index": 0, "content": text}]

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(text):
            end = start + chunk_size

            if end < len(text):
                for i in range(min(end + 200, len(text)), end - 1, -1):
                    if text[i - 1] in '。！？\n':
                        end = i
                        break

            chunk = text[start:end]

            if len(chunk) >= self.MIN_CHUNK_SIZE or end >= len(text):
                chunks.append({
                    "chunk_index": chunk_index,
                    "content": chunk
                })
                chunk_index += 1

            start = end - overlap
            if start >= len(text):
                break

        return chunks

    async def add_document(
        self,
        doc_id: str,
        content: str,
        metadata: Dict[str, Any] = None
    ):
        """添加文档到向量存储（支持分块）。"""
        try:
            await vector_store_service.init_collection()

            chunks = self.chunk_text(content)
            logger.info(f"文档 {doc_id} 分块完成，共 {len(chunks)} 个块")

            if not chunks:
                logger.warning(f"文档 {doc_id} 分块结果为空")
                return

            documents_to_add = []
            for chunk in chunks:
                import uuid
                chunk_id = str(uuid.uuid4())
                embedding = await embedding_service.embed_single(chunk["content"])

                if not embedding:
                    logger.warning(f"块 {chunk_id} 向量化失败")
                    continue

                chunk_metadata = {
                    **(metadata or {}),
                    "original_doc_id": doc_id,
                    "chunk_index": chunk["chunk_index"]
                }

                documents_to_add.append({
                    "doc_id": chunk_id,
                    "content": chunk["content"],
                    "embedding": embedding,
                    "metadata": chunk_metadata
                })

            if not documents_to_add:
                logger.warning(f"文档 {doc_id} 没有有效的块可以添加")
                return

            await vector_store_service.add_documents(documents_to_add)

            logger.info(f"文档 {doc_id} 已分块存储，共 {len(documents_to_add)} 个块")
        except Exception as e:
            logger.error(f"添加文档 {doc_id} 到向量存储失败: {e}")
            raise

    async def add_chunks(
        self,
        doc_id: str,
        chunks: List[Dict[str, Any]],
        base_metadata: Dict[str, Any] = None,
        max_concurrent: int = 3,
    ):
        """将预处理好的 chunks 批量添加到向量存储。

        优化：多个 embedding 批次并行执行，使用信号量控制并发数。

        Args:
            doc_id: 文档 ID
            chunks: [{"content": str, "chunk_index": int, "chunk_type": str, "section_path": str}, ...]
            base_metadata: 基础元数据（filename, file_type 等）
            max_concurrent: 最大并发数（默认3，避免API限流）
        """
        try:
            await vector_store_service.init_collection()

            if not chunks:
                return

            import uuid
            batch_size = 20  # 每批最多 20 个文本嵌入
            semaphore = asyncio.Semaphore(max_concurrent)

            # 分批
            batch_groups = []
            for batch_start in range(0, len(chunks), batch_size):
                batch_chunks = chunks[batch_start:batch_start + batch_size]
                batch_groups.append(batch_chunks)

            async def _embed_batch(batch_idx: int, batch_chunks: List[Dict[str, Any]]):
                """单个批次的嵌入处理"""
                async with semaphore:
                    texts = [c["content"] for c in batch_chunks]
                    try:
                        embeddings = await embedding_service.embed(texts)
                        return batch_idx, batch_chunks, embeddings
                    except Exception as emb_err:
                        logger.warning(f"嵌入批次 {batch_idx} 失败: {emb_err}")
                        return batch_idx, batch_chunks, None

            # 并行执行所有批次
            tasks = [_embed_batch(i, batch) for i, batch in enumerate(batch_groups)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 收集结果
            documents_to_add = []
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(f"嵌入批次异常: {result}")
                    continue

                batch_idx, batch_chunks, embeddings = result
                if embeddings is None:
                    continue

                for chunk, embedding in zip(batch_chunks, embeddings):
                    if not embedding:
                        continue

                    chunk_id = str(uuid.uuid4())
                    metadata = {
                        **(base_metadata or {}),
                        "original_doc_id": doc_id,
                        "chunk_index": chunk.get("chunk_index", 0),
                        "chunk_type": chunk.get("chunk_type", "text"),
                        "section_path": chunk.get("section_path", ""),
                        "source_file": base_metadata.get("filename", "") if base_metadata else "",
                        "file_type": base_metadata.get("file_type", "") if base_metadata else "",
                    }

                    documents_to_add.append({
                        "doc_id": chunk_id,
                        "content": chunk["content"],
                        "embedding": embedding,
                        "metadata": metadata,
                    })

            if documents_to_add:
                await vector_store_service.add_documents(documents_to_add)
                logger.info(f"文档 {doc_id} 批量添加 {len(documents_to_add)} 个 chunks 到向量存储")
        except Exception as e:
            logger.error(f"批量添加 chunks 失败: doc_id={doc_id}, error={e}")
            raise

    # ──────────────────────────── 检索方法 ────────────────────────────

    async def search_relevant_documents(
        self,
        query: str,
        top_k: int = 10,
        rerank_top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """搜索相关文档（按文档ID聚合）。"""
        try:
            query_embedding = await embedding_service.embed_single(query)
            vector_results = await vector_store_service.search(query_embedding, top_k * 3)

            if not vector_results or not isinstance(vector_results, list):
                return []

            valid_results = [r for r in vector_results if isinstance(r, dict) and "content" in r]
            if not valid_results:
                return []

            # 按文档ID聚合
            doc_scores = {}
            for r in valid_results:
                original_doc_id = r.get("metadata", {}).get("original_doc_id", r.get("doc_id", ""))
                score = r.get("score", 0)

                if original_doc_id not in doc_scores or score > doc_scores[original_doc_id]["score"]:
                    doc_scores[original_doc_id] = {
                        "doc_id": original_doc_id,
                        "score": score,
                        "content": r["content"],
                        "metadata": r.get("metadata", {})
                    }

            sorted_docs = sorted(doc_scores.values(), key=lambda x: x["score"], reverse=True)[:top_k]

            if not sorted_docs:
                return []

            # 重排
            documents = [d["content"] for d in sorted_docs]
            rerank_results = await rerank_service.rerank(query, documents, min(rerank_top_n, len(documents)))

            if not rerank_results or not isinstance(rerank_results, list):
                return sorted_docs[:rerank_top_n]

            sorted_results = sorted(rerank_results, key=lambda x: x.get("relevance_score", 0), reverse=True)

            return [
                {
                    **sorted_docs[r["index"]],
                    "rerank_score": r.get("relevance_score", 0)
                }
                for r in sorted_results[:rerank_top_n]
                if "index" in r and r["index"] < len(sorted_docs)
            ]
        except Exception as e:
            logger.error(f"搜索相关文档失败: {e}")
            return []

    async def search_for_field(
        self,
        query: str,
        doc_ids: List[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """为填表字段搜索相关 chunks（带 doc_id 过滤）。

        Args:
            query: 搜索查询
            doc_ids: 限制搜索的文档 ID 列表
            top_k: 返回数量

        Returns:
            [{"content": str, "score": float, "metadata": dict}, ...]
        """
        try:
            query_embedding = await embedding_service.embed_single(query)

            # 构建过滤条件
            filter_conditions = None
            if doc_ids:
                filter_conditions = {"source_file": None}  # 占位，下面替换
                # 用 original_doc_id 过滤
                filter_conditions = {"original_doc_id": doc_ids}

            vector_results = await vector_store_service.search(
                query_embedding,
                top_k=top_k,
                filter_conditions=filter_conditions,
            )

            if not vector_results or not isinstance(vector_results, list):
                return []

            return [r for r in vector_results if isinstance(r, dict) and "content" in r]
        except Exception as e:
            logger.error(f"字段级搜索失败: {e}")
            return []

    async def find_documents_for_template(
        self,
        template_content: str,
        template_structure: Dict[str, Any] = None,
        top_k: int = 10,
        rerank_top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """为模板找到相关文档。"""
        query = template_content
        if template_structure:
            if "headings" in template_structure:
                headings = " ".join([h["text"] for h in template_structure["headings"]])
                query = f"{headings}\n{template_content}"

        return await self.search_relevant_documents(query, top_k, rerank_top_n)

    async def find_related_documents_via_graph(
        self,
        document_ids: List[str],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """通过知识图谱找到关联文档。"""
        if not document_ids:
            return []

        result = await run_cypher(
            """
            MATCH (d1:Document)-[:HAS_ENTITY]->(e:Entity)<-[:HAS_ENTITY]-(d2:Document)
            WHERE d1.id IN $doc_ids AND NOT d2.id IN $doc_ids
            RETURN d2.id AS doc_id, COUNT(e) AS shared_entities, COLLECT(DISTINCT e.name)[..5] AS shared_entity_names
            ORDER BY shared_entities DESC
            LIMIT $limit
            """,
            {"doc_ids": document_ids, "limit": limit}
        )

        return [
            {
                "doc_id": r["doc_id"],
                "shared_entities": r["shared_entities"],
                "shared_entity_names": r["shared_entity_names"]
            }
            for r in result
        ]

    async def auto_select_documents(
        self,
        template_content: str,
        template_structure: Dict[str, Any] = None,
        max_docs: int = 5,
        fallback_to_all: bool = True
    ) -> List[str]:
        """自动选择相关文档。"""
        relevant_docs = await self.find_documents_for_template(
            template_content,
            template_structure,
            top_k=20,
            rerank_top_n=max_docs
        )

        selected_doc_ids = []
        for doc in relevant_docs:
            original_doc_id = doc.get("metadata", {}).get("original_doc_id", doc.get("doc_id"))
            if original_doc_id and original_doc_id not in selected_doc_ids:
                try:
                    from uuid import UUID
                    UUID(original_doc_id)
                    selected_doc_ids.append(original_doc_id)
                except ValueError:
                    continue

        # 通过图谱找到关联文档
        if len(selected_doc_ids) < max_docs:
            related_docs = await self.find_related_documents_via_graph(
                selected_doc_ids,
                limit=max_docs - len(selected_doc_ids)
            )
            for doc in related_docs:
                if doc["doc_id"] not in selected_doc_ids:
                    selected_doc_ids.append(doc["doc_id"])

        # 回退到获取所有源文档
        if not selected_doc_ids and fallback_to_all:
            from app.db.postgres import engine
            from app.models.document import Document
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Document.id, Document.file_path, Document.file_type, Document.original_filename)
                    .where(Document.doc_category == "source")
                    .limit(max_docs)
                )
                docs = result.all()

                for doc_id, file_path, file_type, original_filename in docs:
                    try:
                        from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
                        parsers = {
                            "docx": DocxParser(),
                            "xlsx": XlsxParser(),
                            "md": MdParser(),
                            "txt": TxtParser()
                        }
                        parser = parsers.get(file_type)
                        if parser:
                            parsed = parser.parse(file_path)
                            full_text = parsed.get("full_text", "")
                            if full_text:
                                await self.add_document(
                                    doc_id=str(doc_id),
                                    content=full_text,
                                    metadata={
                                        "filename": original_filename,
                                        "file_type": file_type
                                    }
                                )
                                selected_doc_ids.append(str(doc_id))
                    except Exception as e:
                        logger.warning(f"重新向量化文档 {doc_id} 失败: {e}")

        return selected_doc_ids[:max_docs]


rag_service = RAGService()
