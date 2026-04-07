import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime
import os
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update as sql_update, text
from app.core.config import get_settings
from app.db.postgres import get_db, engine
from app.models.document import Document, ExtractionTask
from app.schemas.document import DocumentResponse
from app.services.preprocessing_service import preprocess_document
from app.services.knowledge_graph_service import knowledge_graph_service

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


async def auto_extract_document(
    doc_id: UUID,
    file_path: str,
    file_type: str,
    original_filename: str
):
    """自动提取文档信息（后台任务）"""
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        task = ExtractionTask(
            task_type="entity_extraction",
            status="processing",
            input_files=[str(doc_id)],
            config={"entity_types": "auto"},
            result={
                "progress": "0%",
                "current_step": "准备中...",
                "total_files": 1,
                "processed_files": 0
            },
            started_at=datetime.utcnow()
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        await _do_extraction(db, AsyncSessionLocal, task, doc_id, file_path, file_type, original_filename)


async def auto_extract_document_with_task(
    doc_id: UUID,
    file_path: str,
    file_type: str,
    original_filename: str,
    task_id: UUID
):
    """使用已存在的任务进行提取（后台任务）"""
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            logger.warning("Extraction task %s not found", task_id)
            return

        await _do_extraction(db, AsyncSessionLocal, task, doc_id, file_path, file_type, original_filename)


async def _do_extraction(
    db,
    AsyncSessionLocal,
    task: ExtractionTask,
    doc_id: UUID,
    file_path: str,
    file_type: str,
    original_filename: str
):
    """执行提取任务的核心逻辑 — 调用预处理流水线"""

    async def update_progress(message: str, progress: str = None):
        try:
            async with AsyncSessionLocal() as progress_db:
                current_result = task.result or {}
                current_result.update({
                    "current_step": message,
                    "progress": progress or current_result.get("progress", "0%"),
                    "updated_at": datetime.utcnow().isoformat()
                })
                stmt = sql_update(ExtractionTask).where(
                    ExtractionTask.id == task.id
                ).values(result=current_result)
                await progress_db.execute(stmt)
                await progress_db.commit()
        except Exception as e:
            logger.error("Progress update error: %s", e)

    try:
        await update_progress(f"正在预处理: {original_filename}", "10%")

        result = await preprocess_document(
            doc_id=str(doc_id),
            file_path=file_path,
            file_type=file_type,
            original_filename=original_filename,
            progress_callback=update_progress,
            base_progress=10,
            progress_range=80,
        )

        await update_progress("正在保存结果...", "95%")

        await db.commit()

        task.status = "completed"
        task.result = {
            "entities_count": result.get("entities_count", 0),
            "chunks_count": result.get("chunks_count", 0),
            "progress": "100%",
            "current_step": "预处理完成"
        }
        task.completed_at = datetime.utcnow()
        await db.commit()

    except Exception as e:
        logger.error("Preprocessing error for %s: %s", doc_id, e, exc_info=True)
        task.status = "failed"
        task.error_message = str(e)
        task.result = {"progress": "100%", "error": str(e), "current_step": "预处理失败"}
        task.completed_at = datetime.utcnow()
        await db.commit()


@router.post("/upload", response_model=List[DocumentResponse])
async def upload_documents(
    files: List[UploadFile] = File(...),
    doc_category: str = "source",
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db)
):
    uploaded_docs = []
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    for file in files:
        file_ext = file.filename.split(".")[-1].lower()
        if file_ext not in ["docx", "xlsx", "md", "txt"]:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

        unique_filename = f"{uuid4().hex}.{file_ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        doc = Document(
            filename=unique_filename,
            original_filename=file.filename,
            file_type=file_ext,
            doc_category=doc_category,
            file_size=len(content),
            file_path=file_path,
            status="uploaded"
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        if doc_category == "source" and background_tasks:
            background_tasks.add_task(
                auto_extract_document,
                doc.id,
                file_path,
                file_ext,
                file.filename
            )

        uploaded_docs.append(doc)

    return uploaded_docs


@router.get("/", response_model=List[dict])
async def list_documents(
    doc_category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    query = select(Document)
    if doc_category:
        query = query.where(Document.doc_category == doc_category)
    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Document.created_at.desc())
    )
    documents = result.scalars().all()

    doc_list = []
    for doc in documents:
        doc_dict = {
            "id": str(doc.id),
            "filename": doc.filename,
            "original_filename": doc.original_filename,
            "file_type": doc.file_type,
            "doc_category": doc.doc_category,
            "file_size": doc.file_size,
            "status": doc.status,
            "metadata_info": doc.metadata_info or {},
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "extraction_status": None
        }

        if doc.doc_category == "source":
            doc_id_str = str(doc.id)
            # 获取提取任务状态
            task_result = await db.execute(
                select(ExtractionTask)
                .where(text("input_files::text LIKE :doc_id"))
                .params(doc_id=f'%"{doc_id_str}"%')
                .order_by(ExtractionTask.created_at.desc())
                .limit(1)
            )
            task = task_result.scalar_one_or_none()

            # 获取提取结果统计
            from app.models.document import DocumentExtraction
            extraction_result = await db.execute(
                select(DocumentExtraction).where(DocumentExtraction.document_id == doc.id)
            )
            extraction = extraction_result.scalar_one_or_none()

            if task or extraction:
                progress = "0%"
                current_step = ""
                entities_count = 0

                if task:
                    if task.result and isinstance(task.result, dict):
                        progress = task.result.get("progress", "0%")
                        current_step = task.result.get("current_step", "")

                if extraction:
                    entities_count = extraction.entities_count

                doc_dict["extraction_status"] = {
                    "task_id": str(task.id) if task else None,
                    "status": task.status if task else "completed",
                    "progress": progress,
                    "current_step": current_step,
                    "error": task.error_message if task else None,
                    "entities_count": entities_count
                }

        doc_list.append(doc_dict)

    return doc_list


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        doc.file_path,
        filename=doc.original_filename,
        media_type="application/octet-stream"
    )


@router.post("/{document_id}/retry-extraction")
async def retry_extraction(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.doc_category != "source":
        raise HTTPException(status_code=400, detail="Only source documents can be extracted")

    doc_id_str = str(document_id)
    await db.execute(
        text("DELETE FROM extraction_tasks WHERE input_files::text LIKE :doc_id"),
        {"doc_id": f'%"{doc_id_str}"%'}
    )

    task = ExtractionTask(
        task_type="entity_extraction",
        status="processing",
        input_files=[doc_id_str],
        config={"entity_types": "auto"},
        result={
            "progress": "0%",
            "current_step": "准备中...",
            "total_files": 1,
            "processed_files": 0
        },
        started_at=datetime.utcnow()
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    background_tasks.add_task(
        auto_extract_document_with_task,
        doc.id,
        doc.file_path,
        doc.file_type,
        doc.original_filename,
        task.id
    )

    return {"message": "重新预处理已启动", "document_id": document_id}


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id_str = str(document_id)

    try:
        # 1. 删除 PostgreSQL extraction_tasks
        await db.execute(
            text("DELETE FROM extraction_tasks WHERE input_files::text LIKE :doc_id"),
            {"doc_id": f'%"{doc_id_str}"%'}
        )

        # 2. 删除 Neo4j 实体和关系
        try:
            await knowledge_graph_service.delete_document_entities(doc_id_str)
        except Exception as e:
            logger.warning("Failed to delete Neo4j entities for document %s: %s", document_id, e)

        # 3. 删除 Qdrant 向量
        try:
            from app.services.vector_store_service import vector_store_service
            await vector_store_service.delete_document(doc_id_str)
        except Exception as e:
            logger.warning("Failed to delete vector store data for document %s: %s", document_id, e)

        # 4. 删除 xlsx 对应的 PostgreSQL 表
        try:
            # 从 PostgreSQL 获取 xlsx schema 信息
            from app.models.document import DocumentExtraction

            result = await db.execute(
                select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
            )
            extraction = result.scalar_one_or_none()

            table_names_to_drop = []

            # 从 PostgreSQL 获取表名
            if extraction and extraction.xlsx_schema:
                for schema in extraction.xlsx_schema:
                    table_name = schema.get("table_name", "")
                    if table_name:
                        table_names_to_drop.append(table_name)

            # 如果 PostgreSQL 中没有，再尝试从内存中获取（兼容旧数据）
            if not table_names_to_drop:
                from app.services.preprocessing_service import get_xlsx_schema_store
                schema_store = get_xlsx_schema_store()
                if doc_id_str in schema_store:
                    for schema in schema_store[doc_id_str]:
                        table_name = schema.get("table_name", "")
                        if table_name:
                            table_names_to_drop.append(table_name)

            # 删除所有相关的表
            for table_name in table_names_to_drop:
                try:
                    from sqlalchemy import text as sa_text
                    async with engine.connect() as conn:
                        await conn.execute(sa_text(f'DROP TABLE IF EXISTS "{table_name}"'))
                        await conn.commit()
                        logger.info(f"Deleted PG table: {table_name}")
                except Exception as e:
                    logger.warning(f"Failed to drop table {table_name}: {e}")

            # 清理内存中的 schema store
            try:
                from app.services.preprocessing_service import get_xlsx_schema_store
                schema_store = get_xlsx_schema_store()
                if doc_id_str in schema_store:
                    del schema_store[doc_id_str]
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Failed to delete xlsx PG tables for document {doc_id_str}: {e}")

        # 5. 删除 PostgreSQL 中的提取结果
        try:
            from app.models.document import DocumentExtraction
            await db.execute(
                text("DELETE FROM document_extractions WHERE document_id = :doc_id"),
                {"doc_id": document_id}
            )
        except Exception as e:
            logger.warning("Failed to delete extraction data for document %s: %s", document_id, e)

        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)

        await db.delete(doc)
        await db.commit()

        return {"message": "文档及相关数据已删除", "document_id": document_id}

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
