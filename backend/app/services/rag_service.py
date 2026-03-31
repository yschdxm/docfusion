from typing import List, Dict, Any, Optional
import logging
from app.services.embedding_service import embedding_service
from app.services.rerank_service import rerank_service
from app.services.vector_store_service import vector_store_service
from app.services.llm_service import llm_service
from app.db.neo4j_db import run_cypher

logger = logging.getLogger(__name__)


class RAGService:
    """RAG服务 - 检索增强生成"""
    
    # 分块参数
    CHUNK_SIZE = 500  # 每块500字
    CHUNK_OVERLAP = 50  # 重叠50字
    MIN_CHUNK_SIZE = 100  # 最小块大小
    
    async def init(self):
        """初始化向量存储"""
        await vector_store_service.init_collection()
    
    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[Dict[str, Any]]:
        """
        将文本分成多个块
        
        Args:
            text: 输入文本
            chunk_size: 块大小（默认500字）
            overlap: 重叠大小（默认50字）
            
        Returns:
            分块结果列表，每项包含chunk_index和content
        """
        chunk_size = chunk_size or self.CHUNK_SIZE
        overlap = overlap or self.CHUNK_OVERLAP
        
        if len(text) <= chunk_size:
            return [{"chunk_index": 0, "content": text}]
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # 如果不是最后一块，尝试在句号、问号、感叹号处断开
            if end < len(text):
                # 向后查找最近的标点符号
                for i in range(min(end + 100, len(text)), end - 1, -1):
                    if text[i-1] in '。！？\n':
                        end = i
                        break
            
            chunk = text[start:end]
            
            # 只保留足够大的块
            if len(chunk) >= self.MIN_CHUNK_SIZE or end >= len(text):
                chunks.append({
                    "chunk_index": chunk_index,
                    "content": chunk
                })
                chunk_index += 1
            
            # 移动到下一个块的起始位置（考虑重叠）
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
        """
        添加文档到向量存储（支持分块）
        
        Args:
            doc_id: 文档ID
            content: 文档内容
            metadata: 元数据
        """
        try:
            # 确保集合存在
            await vector_store_service.init_collection()
            
            # 分块
            chunks = self.chunk_text(content)
            logger.info(f"文档 {doc_id} 分块完成，共 {len(chunks)} 个块")
            
            if not chunks:
                logger.warning(f"文档 {doc_id} 分块结果为空")
                return
            
            # 为每个块生成向量并存储
            documents_to_add = []
            for chunk in chunks:
                # 生成UUID格式的chunk_id
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
            
            # 批量添加
            await vector_store_service.add_documents(documents_to_add)
            
            logger.info(f"文档 {doc_id} 已分块存储，共 {len(documents_to_add)} 个块")
        except Exception as e:
            logger.error(f"添加文档 {doc_id} 到向量存储失败: {e}")
            raise
    
    async def search_relevant_documents(
        self,
        query: str,
        top_k: int = 10,
        rerank_top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        搜索相关文档（按文档ID聚合）
        
        Args:
            query: 查询文本
            top_k: 向量检索返回数量
            rerank_top_n: 重排后返回数量
            
        Returns:
            相关文档列表（按文档ID去重）
        """
        try:
            # 1. 向量检索（搜索更多块）
            query_embedding = await embedding_service.embed_single(query)
            vector_results = await vector_store_service.search(query_embedding, top_k * 3)
            
            if not vector_results:
                return []
            
            # 确保vector_results是列表且元素是字典
            if not isinstance(vector_results, list):
                return []
            
            # 过滤出有效的字典元素
            valid_results = [r for r in vector_results if isinstance(r, dict) and "content" in r]
            
            if not valid_results:
                return []
            
            # 2. 按文档ID聚合，取每个文档的最高分块
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
            
            # 3. 按分数排序，取top_k个文档
            sorted_docs = sorted(doc_scores.values(), key=lambda x: x["score"], reverse=True)[:top_k]
            
            if not sorted_docs:
                return []
            
            # 4. 重排
            documents = [d["content"] for d in sorted_docs]
            rerank_results = await rerank_service.rerank(query, documents, min(rerank_top_n, len(documents)))
            
            if not rerank_results or not isinstance(rerank_results, list):
                return sorted_docs[:rerank_top_n]
            
            # 5. 按相关度排序并返回
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
    
    async def find_documents_for_template(
        self,
        template_content: str,
        template_structure: Dict[str, Any] = None,
        top_k: int = 10,
        rerank_top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        为模板找到相关文档
        
        Args:
            template_content: 模板内容
            template_structure: 模板结构
            top_k: 向量检索返回数量
            rerank_top_n: 重排后返回数量
            
        Returns:
            相关文档列表
        """
        # 构建查询文本
        query = template_content
        if template_structure:
            # 从模板结构中提取关键信息
            if "headings" in template_structure:
                headings = " ".join([h["text"] for h in template_structure["headings"]])
                query = f"{headings}\n{template_content}"
        
        return await self.search_relevant_documents(query, top_k, rerank_top_n)
    
    async def find_related_documents_via_graph(
        self,
        document_ids: List[str],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        通过知识图谱找到关联文档
        
        Args:
            document_ids: 文档ID列表
            limit: 返回数量
            
        Returns:
            关联文档列表
        """
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
        """
        自动选择相关文档
        
        Args:
            template_content: 模板内容
            template_structure: 模板结构
            max_docs: 最大文档数量
            fallback_to_all: 当RAG没有结果时，是否回退到获取所有源文档
            
        Returns:
            文档ID列表
        """
        # 1. 向量检索 + 重排
        relevant_docs = await self.find_documents_for_template(
            template_content,
            template_structure,
            top_k=20,
            rerank_top_n=max_docs
        )
        
        # 使用original_doc_id而不是doc_id
        selected_doc_ids = []
        for doc in relevant_docs:
            original_doc_id = doc.get("metadata", {}).get("original_doc_id", doc.get("doc_id"))
            # 过滤掉测试数据和无效ID
            if original_doc_id and original_doc_id not in selected_doc_ids:
                # 验证是否是有效的UUID格式
                try:
                    from uuid import UUID
                    UUID(original_doc_id)
                    selected_doc_ids.append(original_doc_id)
                except ValueError:
                    logger.warning(f"跳过无效的文档ID: {original_doc_id}")
                    continue
        
        # 2. 通过图谱找到关联文档
        if len(selected_doc_ids) < max_docs:
            related_docs = await self.find_related_documents_via_graph(
                selected_doc_ids,
                limit=max_docs - len(selected_doc_ids)
            )
            for doc in related_docs:
                if doc["doc_id"] not in selected_doc_ids:
                    selected_doc_ids.append(doc["doc_id"])
        
        # 3. 如果还是没有结果，回退到获取所有源文档并重新向量化
        if not selected_doc_ids and fallback_to_all:
            from app.db.postgres import get_db, engine
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
                
                # 尝试重新向量化文档
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
