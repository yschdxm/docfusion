from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, List, Optional
from uuid import UUID, uuid4
from datetime import datetime
import os
import aiofiles
import html
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update as sql_update, text
from app.core.config import get_settings
from app.db.postgres import get_db, engine
from app.models.document import Document, ExtractionTask
from app.schemas.document import DocumentResponse, DocumentPreviewResponse, DocumentSaveRequest
from app.services.knowledge_graph_service import knowledge_graph_service
from app.services.extraction_service import extraction_service
from app.db.mongodb import get_collection
from app.db.neo4j_db import run_cypher
from app.services.document_processor.docx_parser import DocxParser
from app.services.document_processor.md_parser import MdParser
from app.services.document_processor.txt_parser import TxtParser
from app.services.document_processor.xlsx_parser import XlsxParser

settings = get_settings()
router = APIRouter()
TEXT_PREVIEW_LIMIT = 20000
ONLYOFFICE_FILE_TYPES = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}


def _strip_trailing_slash(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


def _get_file_media_type(file_type: str) -> str:
    media_types = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
    }
    return media_types.get(file_type.lower(), "application/octet-stream")


def _build_onlyoffice_document_key(doc: Document) -> str:
    updated = int(doc.updated_at.timestamp()) if doc.updated_at else int(datetime.utcnow().timestamp())
    return f"{doc.id}-{doc.file_size or 0}-{updated}"


def _build_sheet_markdown(sheets: List[dict]) -> str:
    sections: List[str] = []
    for sheet in sheets:
        sections.append(f"# {sheet.get('name', 'Sheet')}")
        rows = sheet.get("data") or []
        for row in rows[:50]:
            sections.append(" | ".join(str(cell or "") for cell in row))
        if len(rows) > 50:
            sections.append(f"... ({len(rows) - 50} more rows)")
        sections.append("")
    return "\n".join(sections).strip()


def _truncate_text(content: str, limit: int = TEXT_PREVIEW_LIMIT) -> tuple[str, bool]:
    if len(content) <= limit:
        return content, False
    return content[:limit], True


def _get_document_preview(doc: Document) -> DocumentPreviewResponse:
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_type = (doc.file_type or "").lower()

    if file_type == "pdf":
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="pdf",
            can_edit=False,
        )

    if file_type == "txt":
        parsed = TxtParser.parse(doc.file_path)
        content, truncated = _truncate_text(parsed.get("full_text", ""))
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="text",
            content=content,
            truncated=truncated,
            can_edit=True,
        )

    if file_type == "md":
        parsed = MdParser.parse(doc.file_path)
        content, truncated = _truncate_text(parsed.get("full_text", ""))
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="markdown",
            content=content,
            html_content=parsed.get("html", ""),
            truncated=truncated,
            can_edit=True,
        )

    if file_type in ONLYOFFICE_FILE_TYPES and settings.ONLYOFFICE_ENABLED:
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="onlyoffice",
            can_edit=False,
        )

    if file_type == "docx":
        parsed = DocxParser.parse(doc.file_path)
        content, truncated = _truncate_text(parsed.get("full_text", ""))
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="text",
            content=content,
            truncated=truncated,
            can_edit=False,
        )

    if file_type == "xlsx":
        parsed = XlsxParser.parse(doc.file_path)
        sheets = parsed.get("sheets", [])
        sheet_text, truncated = _truncate_text(_build_sheet_markdown(sheets))
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="spreadsheet",
            content=sheet_text,
            truncated=truncated,
            can_edit=False,
            sheets=sheets[:5],
        )

    raise HTTPException(status_code=400, detail=f"Preview not supported for file type: {file_type}")


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
            config={"entity_types": ["PERSON", "LOCATION", "ORGANIZATION", "DATE", "NUMBER"]},
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
            print(f"Task {task_id} not found")
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
    """执行提取任务的核心逻辑"""
    
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
            print(f"Progress update error: {e}")
    
    try:
        await update_progress(f"正在提取: {original_filename}", "10%")
        
        extraction_result = await extraction_service.extract_from_document(
            file_path=file_path,
            file_type=file_type,
            entity_types=["PERSON", "LOCATION", "ORGANIZATION", "DATE", "NUMBER"],
            progress_callback=update_progress,
            base_progress=10,
            progress_range=80
        )
        
        await update_progress("正在保存结果...", "90%")
        
        await extraction_service.save_to_mongodb(doc_id, extraction_result)
        
        try:
            await knowledge_graph_service.build_graph_from_entities(
                str(doc_id),
                extraction_result.get("entities", [])
            )
        except Exception as kg_error:
            print(f"Knowledge graph build error: {kg_error}")
        
        await db.commit()
        
        task.status = "completed"
        task.result = {
            "entities_count": len(extraction_result.get("entities", [])),
            "progress": "100%",
            "current_step": "提取完成"
        }
        task.completed_at = datetime.utcnow()
        await db.commit()
        
    except Exception as e:
        print(f"Auto extraction error for {doc_id}: {e}")
        task.status = "failed"
        task.error_message = str(e)
        task.result = {"progress": "100%", "error": str(e), "current_step": "提取失败"}
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
            task_result = await db.execute(
                select(ExtractionTask)
                .where(text("input_files::text LIKE :doc_id"))
                .params(doc_id=f'%"{doc_id_str}"%')
                .order_by(ExtractionTask.created_at.desc())
                .limit(1)
            )
            task = task_result.scalar_one_or_none()
            if task:
                progress = "0%"
                current_step = ""
                if task.result and isinstance(task.result, dict):
                    progress = task.result.get("progress", "0%")
                    current_step = task.result.get("current_step", "")
                
                doc_dict["extraction_status"] = {
                    "task_id": str(task.id),
                    "status": task.status,
                    "progress": progress,
                    "current_step": current_step,
                    "error": task.error_message,
                    "entities_count": task.result.get("entities_count", 0) if task.result else 0
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


@router.get("/{document_id}/preview", response_model=DocumentPreviewResponse)
async def preview_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return _get_document_preview(doc)


@router.get("/{document_id}/office-config")
async def get_onlyoffice_config(
    document_id: UUID,
    mode: str = "view",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_type = (doc.file_type or "").lower()
    if file_type not in ONLYOFFICE_FILE_TYPES:
        raise HTTPException(status_code=400, detail="Current file type is not supported by OnlyOffice")

    if not settings.ONLYOFFICE_ENABLED:
        raise HTTPException(status_code=400, detail="OnlyOffice is not enabled")

    server_url = _strip_trailing_slash(settings.ONLYOFFICE_DOCUMENT_SERVER_URL)
    callback_base = _strip_trailing_slash(settings.ONLYOFFICE_CALLBACK_BASE_URL)
    editor_mode = "edit" if mode.lower() == "edit" else "view"

    document_type = "word"
    if file_type in {"xls", "xlsx"}:
        document_type = "cell"
    elif file_type in {"ppt", "pptx"}:
        document_type = "slide"

    config = {
        "documentType": document_type,
        "type": "desktop",
        "document": {
            "title": doc.original_filename,
            "url": f"{callback_base}/api/v1/documents/{doc.id}/raw",
            "fileType": file_type,
            "key": _build_onlyoffice_document_key(doc),
            "permissions": {
                "edit": True,
                "download": True,
                "print": True,
                "copy": True,
                "comment": True,
            },
        },
        "editorConfig": {
            "mode": editor_mode,
            "lang": "zh-CN",
            "callbackUrl": f"{callback_base}/api/v1/documents/onlyoffice/callback/{doc.id}",
            "user": {
                "id": "docfusion-user",
                "name": "DocFusion User",
            },
        },
    }

    return {
        "serverUrl": server_url,
        "config": config,
    }


@router.post("/onlyoffice/callback/{document_id}")
async def onlyoffice_callback(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": 1}

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        payload = {}
    status = payload.get("status")
    if status not in {2, 6}:
        return {"error": 0}

    download_url = payload.get("url")
    if not isinstance(download_url, str) or not download_url:
        return {"error": 0}

    if not doc.file_path:
        return {"error": 1}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(download_url)
            response.raise_for_status()

        async with aiofiles.open(doc.file_path, "wb") as output_file:
            await output_file.write(response.content)

        doc.file_size = len(response.content)
        doc.status = "updated"
        await db.commit()
        return {"error": 0}
    except Exception as exc:
        print(f"OnlyOffice callback error for {document_id}: {exc}")
        await db.rollback()
        return {"error": 1}


@router.get("/{document_id}/raw")
async def raw_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        doc.file_path,
        filename=doc.original_filename,
        media_type=_get_file_media_type((doc.file_type or "").lower())
    )


@router.get("/{document_id}/inline")
async def inline_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_type = (doc.file_type or "").lower()
    if file_type == "pdf":
        return FileResponse(doc.file_path, media_type="application/pdf")

    if file_type == "md":
        parsed = MdParser.parse(doc.file_path)
        return HTMLResponse(parsed.get("html", ""))

    if file_type in {"txt", "docx"}:
        preview = _get_document_preview(doc)
        escaped = html.escape(preview.content)
        return HTMLResponse(
            "<!doctype html><html><head><meta charset='utf-8' />"
            f"<title>{html.escape(doc.original_filename)}</title>"
            "<style>body{margin:0;padding:24px;background:#0f172a;color:#e2e8f0;"
            "font-family:Consolas,'Microsoft YaHei',sans-serif;line-height:1.7}"
            "pre{white-space:pre-wrap;word-break:break-word}</style></head>"
            f"<body><pre>{escaped}</pre></body></html>"
        )

    raise HTTPException(status_code=400, detail="Inline preview is not supported for this file type")


@router.post("/{document_id}/save")
async def save_document_content(
    document_id: UUID,
    payload: DocumentSaveRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_type = (doc.file_type or "").lower()
    if file_type == "txt":
        TxtParser.write(payload.content, doc.file_path)
    elif file_type == "md":
        MdParser.write(payload.content, doc.file_path)
    else:
        raise HTTPException(status_code=400, detail="Only txt and md files support direct editing")

    doc.file_size = len(payload.content.encode("utf-8"))
    doc.status = "updated"
    await db.commit()
    await db.refresh(doc)

    return {
        "message": "Document saved successfully",
        "document": {
            "id": str(doc.id),
            "file_size": doc.file_size,
            "status": doc.status,
            "updated_at": datetime.utcnow().isoformat(),
        },
    }


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
        config={"entity_types": ["PERSON", "LOCATION", "ORGANIZATION", "DATE", "NUMBER"]},
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
    
    return {"message": "重新提取已启动", "document_id": document_id}


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
        await db.execute(
            text("DELETE FROM extraction_tasks WHERE input_files::text LIKE :doc_id"),
            {"doc_id": f'%"{doc_id_str}"%'}
        )
        
        try:
            # 先删除Document节点及其HAS_ENTITY关系
            await run_cypher(
                """
                MATCH (d:Document {id: $doc_id})
                DETACH DELETE d
                """,
                {"doc_id": doc_id_str}
            )
            # 然后删除不再被任何Document引用的Entity节点
            await run_cypher(
                """
                MATCH (e:Entity)
                WHERE NOT (e)<-[:HAS_ENTITY]-()
                DETACH DELETE e
                """,
                {}
            )
        except Exception as e:
            print(f"Neo4j delete error: {e}")
        
        try:
            collection = get_collection("extractions")
            if collection:
                await collection.delete_one({"document_id": doc_id_str})
        except Exception as e:
            print(f"MongoDB delete error: {e}")
        
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
        
        await db.delete(doc)
        await db.commit()
        
        return {"message": "文档及相关数据已删除", "document_id": document_id}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
