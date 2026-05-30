"""预处理流水线 — 文档上传后触发，编排解析→分块→嵌入→入库→实体提取→图谱构建

优化特性：
- xlsx 文件只加载一次 workbook，各步骤复用
- PostgreSQL 入库使用单连接 + 单事务提交
- 流式读取 + 分批处理，内存占用 O(BATCH_SIZE)
- 索引延迟到最后统一创建
"""
import logging
from typing import Dict, Any, Optional, Callable, List
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
from app.services.rag_service import rag_service
from app.services.knowledge_graph_service import knowledge_graph_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


# 解析器映射
PARSERS = {
    "docx": DocxParser(),
    "xlsx": XlsxParser(),
    "md": MdParser(),
    "txt": TxtParser(),
}

# 全局 schema 存储（预处理时写入，填表时读取）
# key: doc_id, value: [{table_name, sheet_name, columns, row_count}]
_xlsx_schema_store: Dict[str, List[Dict[str, Any]]] = {}


def get_xlsx_schema_store() -> Dict[str, List[Dict[str, Any]]]:
    """获取 xlsx schema 存储（供 sql_query_service 使用）。"""
    return _xlsx_schema_store


async def preprocess_document(
    doc_id: str,
    file_path: str,
    file_type: str,
    original_filename: str,
    progress_callback: Optional[Callable] = None,
    base_progress: int = 0,
    progress_range: int = 100,
) -> Dict[str, Any]:
    """预处理流水线主入口。

    Steps:
    1. 解析文档 → 获取 chunks
    2. xlsx：入 PostgreSQL + 生成元数据摘要 chunks
    3. 所有 chunks → 嵌入 → 入 Qdrant
    4. LLM 提取实体+关系（xlsx 用规则提取）
    5. 入 Neo4j
    6. xlsx schema 入内存存储
    """
    parser = PARSERS.get(file_type)
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")

    # ── Step 1: 解析文档 ──
    if progress_callback:
        await progress_callback("正在解析文档...", f"{base_progress}%")

    # 对于 xlsx，只加载一次 workbook，后续步骤复用
    workbook = None
    if file_type == "xlsx":
        workbook = XlsxParser.load_workbook_once(file_path)
        parsed_data = XlsxParser.parse(workbook=workbook)
    else:
        parsed_data = parser.parse(file_path)

    chunks = parsed_data.get("chunks", [])
    full_text = parsed_data.get("full_text", "")

    # 如果解析器没有生成 chunks（旧版），用 RAG 服务的分块
    if not chunks and full_text:
        rag_chunks = rag_service.chunk_text(full_text)
        chunks = [
            {
                "content": c["content"],
                "chunk_index": c["chunk_index"],
                "chunk_type": "text",
                "section_path": "",
            }
            for c in rag_chunks
        ]

    # ── Step 2: xlsx 双轨处理 ──
    schema_info = []
    if file_type == "xlsx":
        # Track 1: 元数据摘要 chunks（复用 workbook）
        if progress_callback:
            await progress_callback("正在生成表格摘要...", f"{base_progress + 5}%")
        try:
            summary_chunks = XlsxParser.generate_metadata_summary(workbook=workbook, doc_id=doc_id)
            chunks = summary_chunks + chunks  # 摘要在前
        except Exception as e:
            logger.warning(f"生成 xlsx 元数据摘要失败: {e}")

        # Track 2: 入 PostgreSQL（复用 workbook，单连接 + 单事务）
        if progress_callback:
            await progress_callback("正在导入表格数据...", f"{base_progress + 10}%")
        try:
            from app.db.postgres import engine
            from sqlalchemy import text as sa_text

            # 使用单连接 + 单事务提交
            async with engine.connect() as conn:
                async def db_execute_in_conn(sql: str, params=None):
                    if params:
                        await conn.execute(sa_text(sql), params)
                    else:
                        await conn.execute(sa_text(sql))

                async def db_execute_many_in_conn(sql: str, param_list: list):
                    await conn.execute(sa_text(sql), param_list)

                schema_info = await XlsxParser.load_to_postgres(
                    workbook=workbook,
                    doc_id=doc_id,
                    db_execute=db_execute_in_conn,
                    db_execute_many=db_execute_many_in_conn,
                    conn=conn,
                )

                # 统一提交事务
                await conn.commit()

            if schema_info:
                _xlsx_schema_store[doc_id] = schema_info
                logger.info(f"xlsx schema 已存储: doc_id={doc_id}, tables={len(schema_info)}")

                # 立即保存 xlsx_schema 到数据库，确保删除时能找到表名
                try:
                    from app.models.document import DocumentExtraction
                    from sqlalchemy import select
                    from sqlalchemy.ext.asyncio import async_sessionmaker
                    from app.db.postgres import engine
                    from uuid import UUID

                    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
                    async with AsyncSessionLocal() as session:
                        # 将字符串 doc_id 转换为 UUID
                        doc_uuid = UUID(doc_id) if isinstance(doc_id, str) else doc_id

                        result = await session.execute(
                            select(DocumentExtraction).where(DocumentExtraction.document_id == doc_uuid)
                        )
                        existing = result.scalar_one_or_none()

                        if existing:
                            existing.xlsx_schema = schema_info
                            existing.updated_at = None
                        else:
                            extraction = DocumentExtraction(
                                document_id=doc_uuid,
                                entities_count=0,
                                relations_count=0,
                                chunks_count=0,
                                xlsx_schema=schema_info,
                            )
                            session.add(extraction)

                        await session.commit()
                        logger.info(f"xlsx_schema 已提前保存到数据库: doc_id={doc_id}")
                except Exception as e:
                    logger.warning(f"提前保存 xlsx_schema 失败: {e}")
        except Exception as e:
            logger.error(f"xlsx 入 PostgreSQL 失败: {e}")
        finally:
            # 关闭 workbook
            if workbook:
                workbook.close()
                workbook = None

    # ── Step 3: 嵌入 + 入向量库 ──
    if progress_callback:
        await progress_callback(f"正在向量化 {len(chunks)} 个文本块...", f"{base_progress + 20}%")

    base_metadata = {
        "filename": original_filename,
        "file_type": file_type,
    }

    try:
        await rag_service.add_chunks(
            doc_id=doc_id,
            chunks=chunks,
            base_metadata=base_metadata,
        )
    except Exception as e:
        logger.error(f"向量化失败: doc_id={doc_id}, error={e}")
        # 向量化失败不中断流程，但记录错误

    # ── Step 4: 实体关系提取 ──
    if progress_callback:
        await progress_callback("正在提取实体关系...", f"{base_progress + 50}%")

    all_entities = []
    all_relations = []

    if file_type == "xlsx":
        # xlsx 用规则提取
        try:
            sheets = parsed_data.get("sheets", [])
            # 使用文件名作为文档标题
            document_title = original_filename
            if document_title and "." in document_title:
                document_title = document_title.rsplit(".", 1)[0]
            await knowledge_graph_service.build_graph_from_xlsx(doc_id, sheets, document_title)
        except Exception as e:
            logger.error(f"xlsx 规则提取失败: {e}")
    else:
        # 非 xlsx 用 LLM 提取
        chunk_batches = _merge_chunks_for_ner(chunks, max_chars=60000)

        for batch_idx, batch_text in enumerate(chunk_batches):
            progress_pct = base_progress + 50 + int((batch_idx / max(len(chunk_batches), 1)) * 30)
            if progress_callback:
                await progress_callback(
                    f"正在提取实体关系 ({batch_idx + 1}/{len(chunk_batches)})...",
                    f"{progress_pct}%"
                )
            try:
                result = await llm_service.extract_entities_and_relations(batch_text)
                batch_entities = result.get("entities", [])
                batch_relations = result.get("relations", [])
                all_entities.extend(batch_entities)
                all_relations.extend(batch_relations)
                logger.info("[PREPROCESS] Batch %d: 提取 %d 实体, %d 关系",
                           batch_idx, len(batch_entities), len(batch_relations))
            except Exception as e:
                logger.error(f"NER 提取失败: batch={batch_idx}, error={e}")

    # ── Step 5: 入知识图谱 ──
    if progress_callback:
        await progress_callback("正在构建知识图谱...", f"{base_progress + 85}%")

    # 统计有attributes的实体
    entities_with_attrs = sum(1 for e in all_entities if e.get("attributes"))
    logger.info("[PREPROCESS] 总共提取 %d 个实体，其中 %d 个有attributes (%.1f%%)",
               len(all_entities), entities_with_attrs,
               100*entities_with_attrs/len(all_entities) if all_entities else 0)

    if all_entities or all_relations:
        try:
            await knowledge_graph_service.build_graph_from_entities(
                doc_id, all_entities, all_relations
            )
            logger.info("[PREPROCESS] 知识图谱构建完成")
        except Exception as e:
            logger.error(f"知识图谱构建失败: {e}")

    # ── Step 6: 保存到 PostgreSQL ──
    try:
        from app.models.document import DocumentExtraction
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from app.db.postgres import engine

        # 创建异步会话
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        async with AsyncSessionLocal() as session:
            # 检查是否已存在记录
            result = await session.execute(
                select(DocumentExtraction).where(DocumentExtraction.document_id == doc_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # 更新现有记录
                existing.entities_count = len(all_entities)
                existing.relations_count = len(all_relations)
                existing.chunks_count = len(chunks)
                existing.xlsx_schema = schema_info
                existing.updated_at = None  # 让 onupdate 自动处理
            else:
                # 创建新记录
                extraction = DocumentExtraction(
                    document_id=doc_id,
                    entities_count=len(all_entities),
                    relations_count=len(all_relations),
                    chunks_count=len(chunks),
                    xlsx_schema=schema_info,
                )
                session.add(extraction)

            await session.commit()
    except Exception as e:
        logger.warning(f"PostgreSQL 保存提取结果失败: {e}")

    if progress_callback:
        await progress_callback(
            f"完成，共 {len(all_entities)} 个实体，{len(chunks)} 个文本块",
            f"{base_progress + progress_range}%",
        )

    return {
        "entities_count": len(all_entities),
        "relations_count": len(all_relations),
        "chunks_count": len(chunks),
        "xlsx_schema": schema_info,
        "full_text": full_text,
        "parsed_data": parsed_data,
    }


def _merge_chunks_for_ner(chunks: List[Dict[str, Any]], max_chars: int = 60000) -> List[str]:
    """将多个 chunks 合并为不超过 max_chars 的批次文本。"""
    batches = []
    current_batch = []
    current_len = 0

    for chunk in chunks:
        content = chunk.get("content", "")
        if current_len + len(content) > max_chars and current_batch:
            batches.append("\n\n".join(current_batch))
            current_batch = []
            current_len = 0
        current_batch.append(content)
        current_len += len(content)

    if current_batch:
        batches.append("\n\n".join(current_batch))

    return batches if batches else [""]
