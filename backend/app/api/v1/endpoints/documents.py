import logging
import time
import hmac
import hashlib
import html
import json
import httpx
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from typing import Any, List, Optional
from uuid import UUID, uuid4
from datetime import datetime
import os
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update as sql_update, text, or_
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.db.postgres import get_db, engine
from app.models.document import Document, ExtractionTask
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentPreviewResponse, DocumentSaveRequest
from app.services.preprocessing_service import preprocess_document
from app.services.knowledge_graph_service import knowledge_graph_service

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()
TEXT_PREVIEW_LIMIT = 20000
ONLYOFFICE_FILE_TYPES = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))


def _strip_trailing_slash(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


def _user_doc_filter(user_id: UUID):
    """构建用户文档过滤条件，根据配置决定是否包含无主数据和共享文档"""
    if settings.INCLUDE_ORPHAN_DATA:
        return or_(Document.user_id == user_id, Document.user_id.is_(None), Document.is_shared == True)
    return or_(Document.user_id == user_id, Document.is_shared == True)


async def _get_user_document(document_id: UUID, user_id: UUID, db: AsyncSession) -> Document:
    """获取文档并确保属于当前用户（或为无主数据）"""
    result = await db.execute(
        select(Document).where(Document.id == document_id, _user_doc_filter(user_id))
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


async def _get_document_as_admin(document_id: UUID, user_id: UUID, db: AsyncSession, is_admin: bool = False) -> Document:
    """获取文档：管理员可访问任意文档，普通用户遵循原有权限"""
    if is_admin:
        result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
    else:
        result = await db.execute(
            select(Document).where(Document.id == document_id, _user_doc_filter(user_id))
        )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _ensure_document_owner(doc: Document, user_id: UUID, is_admin: bool = False):
    """确保用户是文档所有者（或管理员），共享文档对非所有者只读"""
    if is_admin:
        return
    if doc.user_id != user_id:
        raise HTTPException(status_code=403, detail="共享文档只读，无法修改或删除")


def _normalize_api_prefix(prefix: str) -> str:
    normalized = (prefix or "").strip()
    if not normalized or normalized == "/":
        return ""
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/")


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


def _resolve_document_path(file_path: str | None) -> str | None:
    if not file_path:
        return None

    normalized = os.path.normpath(file_path)
    candidates: list[str] = []

    if os.path.isabs(normalized):
        candidates.append(normalized)
    else:
        trimmed = normalized.lstrip(".\\/")
        candidates.extend(
            [
                os.path.abspath(normalized),
                os.path.abspath(os.path.join(BACKEND_ROOT, normalized)),
                os.path.abspath(os.path.join(BACKEND_ROOT, trimmed)),
                os.path.abspath(os.path.join(PROJECT_ROOT, normalized)),
                os.path.abspath(os.path.join(PROJECT_ROOT, trimmed)),
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.exists(candidate):
            return candidate

    return candidates[0] if candidates else None


def _build_onlyoffice_document_key(doc: Document) -> str:
    updated = int(doc.updated_at.timestamp()) if doc.updated_at else int(datetime.utcnow().timestamp())
    return f"{doc.id}-{doc.file_size or 0}-{updated}"


def _onlyoffice_signing_secret() -> str:
    return (settings.ONLYOFFICE_PUBLIC_SIGNING_SECRET or settings.SECRET_KEY or "docfusion-onlyoffice-secret").strip()


def _build_onlyoffice_raw_token(document_id: UUID, expires: int) -> str:
    msg = f"{document_id}:{expires}".encode("utf-8")
    return hmac.new(_onlyoffice_signing_secret().encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _verify_onlyoffice_raw_token(document_id: UUID, expires: int, token: str) -> bool:
    if not token:
        return False
    if expires < int(time.time()):
        return False
    expected = _build_onlyoffice_raw_token(document_id, expires)
    return hmac.compare_digest(expected, token)


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


def _get_document_preview(doc: Document, user_can_edit: bool = True) -> DocumentPreviewResponse:
    from app.services.document_processor.md_parser import MdParser
    from app.services.document_processor.txt_parser import TxtParser

    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    file_type = (doc.file_type or "").lower()

    if file_type == "pdf":
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="pdf",
            can_edit=False,
        )

    if file_type == "txt":
        parsed = TxtParser.parse(resolved_path)
        content, truncated = _truncate_text(parsed.get("full_text", ""))
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="text",
            content=content,
            truncated=truncated,
            can_edit=user_can_edit,
        )

    if file_type == "md":
        parsed = MdParser.parse(resolved_path)
        content, truncated = _truncate_text(parsed.get("full_text", ""))
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="markdown",
            content=content,
            html_content=parsed.get("html", ""),
            truncated=truncated,
            can_edit=user_can_edit,
        )

    # docx / xlsx / ppt 等 Office 文件统一走 OnlyOffice
    if file_type in ONLYOFFICE_FILE_TYPES:
        if not settings.ONLYOFFICE_ENABLED:
            raise HTTPException(status_code=503, detail="OnlyOffice 服务未启用，无法预览 Office 文件")
        return DocumentPreviewResponse(
            file_name=doc.original_filename,
            file_type=file_type,
            preview_type="onlyoffice",
            can_edit=user_can_edit,
        )

    raise HTTPException(status_code=400, detail=f"不支持预览此文件类型: {file_type}")


async def auto_extract_document(
    doc_id: UUID,
    file_path: str,
    file_type: str,
    original_filename: str,
    user_id: UUID = None
):
    """自动提取文档信息（后台任务）"""

    # 检查文件是否存在（任务可能在等待信号量时文件被删除）
    if not os.path.exists(file_path):
        logger.warning(f"文件已不存在，跳过处理: {file_path}")
        return

    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        # 查找已存在的任务记录（上传时创建的）
        doc_id_str = str(doc_id)
        result = await db.execute(
            select(ExtractionTask)
            .where(text("input_files::text LIKE :doc_id"))
            .params(doc_id=f'%"{doc_id_str}"%')
            .order_by(ExtractionTask.created_at.desc())
            .limit(1)
        )
        task = result.scalar_one_or_none()

        if not task:
            # 如果没有找到，创建新任务
            task = ExtractionTask(
                task_type="entity_extraction",
                status="processing",
                user_id=user_id,
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
        else:
            # 更新已有任务状态为处理中
            task.status = "processing"
            task.result = {
                "progress": "0%",
                "current_step": "准备中...",
                "total_files": 1,
                "processed_files": 0
            }

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    uploaded_docs = []
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    for file in files:
        file_ext = file.filename.split(".")[-1].lower()
        if file_ext not in ["docx", "xlsx", "md", "txt"]:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

        unique_filename = f"{uuid4().hex}.{file_ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

        # 流式读取文件，减少内存占用
        file_size = 0
        async with aiofiles.open(file_path, "wb") as f:
            while True:
                chunk = await file.read(8192)  # 每次读取 8KB
                if not chunk:
                    break
                await f.write(chunk)
                file_size += len(chunk)

        doc = Document(
            user_id=current_user.id,
            filename=unique_filename,
            original_filename=file.filename,
            file_type=file_ext,
            doc_category=doc_category,
            file_size=file_size,
            file_path=file_path,
            status="uploaded"
        )
        db.add(doc)
        await db.flush()  # 先 flush 获取 ID，最后统一 commit

        if doc_category == "source":
            # 立即创建 ExtractionTask 记录，让前端能看到"处理中"状态
            task = ExtractionTask(
                task_type="entity_extraction",
                status="queued",  # 先标记为排队中
                user_id=current_user.id,
                input_files=[str(doc.id)],
                config={"entity_types": "auto"},
                result={
                    "progress": "0%",
                    "current_step": "等待处理...",
                    "total_files": 1,
                    "processed_files": 0
                },
                started_at=datetime.utcnow()
            )
            db.add(task)

        uploaded_docs.append(doc)

    # 所有文件统一 commit，减少数据库交互次数
    await db.commit()
    for doc in uploaded_docs:
        await db.refresh(doc)

    # 提交后再启动后台任务
    for doc in uploaded_docs:
        if doc.doc_category == "source":
            asyncio.create_task(
                _queued_extract_document(
                    doc.id,
                    doc.file_path,
                    doc.file_type,
                    doc.original_filename,
                    current_user.id,
                )
            )

    return uploaded_docs


async def _queued_extract_document(
    doc_id: UUID,
    file_path: str,
    file_type: str,
    original_filename: str,
    user_id: UUID = None
):
    """通过任务队列执行文档提取（限制并发数）"""
    from app.services.task_queue import enqueue_task

    await enqueue_task(
        auto_extract_document,
        doc_id,
        file_path,
        file_type,
        original_filename,
        user_id,
        doc_id=str(doc_id),
        task_name=f"extract_{original_filename}",
    )


@router.get("/", response_model=List[dict])
@router.get("", response_model=List[dict])
async def list_documents(
    doc_category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Document).where(_user_doc_filter(current_user.id))
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
            "extraction_status": None,
            "user_id": str(doc.user_id) if doc.user_id else None,
            "is_shared": bool(doc.is_shared),
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


@router.get("/queue-status")
async def get_queue_status(
    current_user: User = Depends(get_current_user)
):
    """获取任务队列状态"""
    from app.services.task_queue import get_queue_status
    return get_queue_status()


@router.get("/{document_id}/progress-stream")
async def progress_stream(
    document_id: UUID,
    request: Request,
):
    """SSE 端点：实时推送文档提取进度。

    使用 Server-Sent Events 替代前端轮询，减少数据库查询压力。
    """
    async def event_generator():
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        last_progress = None
        not_found_count = 0

        while True:
            # 检查客户端是否断开连接
            if await request.is_disconnected():
                break

            try:
                async with AsyncSessionLocal() as db:
                    # 查询最新的提取任务
                    doc_id_str = str(document_id)
                    task_result = await db.execute(
                        select(ExtractionTask)
                        .where(text("input_files::text LIKE :doc_id"))
                        .params(doc_id=f'%"{doc_id_str}"%')
                        .order_by(ExtractionTask.created_at.desc())
                        .limit(1)
                    )
                    task = task_result.scalar_one_or_none()

                    if task and task.result and isinstance(task.result, dict):
                        not_found_count = 0
                        current_progress = task.result.get("progress", "0%")
                        current_step = task.result.get("current_step", "")

                        # 只在进度变化时发送
                        progress_data = {
                            "task_id": str(task.id),
                            "status": task.status,
                            "progress": current_progress,
                            "current_step": current_step,
                            "error": task.error_message,
                        }

                        progress_key = f"{task.status}:{current_progress}"
                        if progress_key != last_progress:
                            yield f"data: {json.dumps(progress_data)}\n\n"
                            last_progress = progress_key

                        # 任务完成或失败时，发送 done 事件通知客户端可以关闭连接
                        if task.status in ("completed", "failed"):
                            yield "event: done\ndata: {}\n\n"
                            # 等待客户端处理完成后关闭连接
                            for _ in range(30):  # 最多等待 30 秒
                                if await request.is_disconnected():
                                    break
                                await asyncio.sleep(1)
                            break
                    else:
                        not_found_count += 1
                        # 如果超过 10 次未找到任务（10秒），可能是任务还未创建或已删除
                        if not_found_count > 10:
                            yield f"data: {json.dumps({'status': 'not_found', 'progress': '0%', 'current_step': '等待任务创建...'})}\n\n"
                            not_found_count = 0
            except Exception as e:
                logger.error(f"SSE progress stream error: {e}")
                # 发送错误事件给客户端
                try:
                    yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
                except Exception:
                    pass

            await asyncio.sleep(1)  # 每秒检查一次

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{document_id}/preview", response_model=DocumentPreviewResponse)
async def preview_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    is_admin = current_user.role in ('admin', 'super_admin')
    doc = await _get_document_as_admin(document_id, current_user.id, db, is_admin)
    # 所有者或管理员可编辑，共享文档对普通用户只读
    user_can_edit = is_admin or doc.user_id == current_user.id
    return _get_document_preview(doc, user_can_edit=user_can_edit)


@router.get("/{document_id}/office-config")
async def get_onlyoffice_config(
    document_id: UUID,
    mode: str = "view",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    is_admin = current_user.role in ('admin', 'super_admin')
    doc = await _get_document_as_admin(document_id, current_user.id, db, is_admin)

    # 共享文档对非所有者强制只读
    if not is_admin and doc.user_id != current_user.id:
        mode = "view"

    file_type = (doc.file_type or "").lower()
    if file_type not in ONLYOFFICE_FILE_TYPES:
        raise HTTPException(status_code=400, detail="Current file type is not supported by OnlyOffice")

    if not settings.ONLYOFFICE_ENABLED:
        raise HTTPException(status_code=400, detail="OnlyOffice is not enabled")

    server_url = _strip_trailing_slash(settings.ONLYOFFICE_DOCUMENT_SERVER_URL)
    callback_base = _strip_trailing_slash(settings.ONLYOFFICE_CALLBACK_BASE_URL)
    api_prefix = _normalize_api_prefix(settings.ONLYOFFICE_API_PREFIX)
    editor_mode = "edit" if mode.lower() == "edit" else "view"

    document_type = "word"
    if file_type in {"xls", "xlsx"}:
        document_type = "cell"
    elif file_type in {"ppt", "pptx"}:
        document_type = "slide"

    ttl_seconds = max(60, int(settings.ONLYOFFICE_PUBLIC_FILE_TTL_SECONDS or 900))
    expires = int(time.time()) + ttl_seconds
    token = _build_onlyoffice_raw_token(doc.id, expires)
    public_raw_url = f"{callback_base}{api_prefix}/documents/onlyoffice/raw-public/{doc.id}?expires={expires}&token={token}"

    config = {
        "documentType": document_type,
        "type": "desktop",
        "document": {
            "title": doc.original_filename,
            "url": public_raw_url,
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
            "callbackUrl": f"{callback_base}{api_prefix}/documents/onlyoffice/callback/{doc.id}",
            "user": {
                "id": str(current_user.id),
                "name": current_user.username,
            },
        },
    }

    return {
        "serverUrl": server_url,
        "config": config,
    }


@router.get("/onlyoffice/raw-public/{document_id}")
async def raw_public_document(
    document_id: UUID,
    expires: int,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    if not _verify_onlyoffice_raw_token(document_id, expires, token):
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        resolved_path,
        filename=doc.original_filename,
        media_type=_get_file_media_type((doc.file_type or "").lower())
    )


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
        logger.error("OnlyOffice callback error for %s: %s", document_id, exc)
        await db.rollback()
        return {"error": 1}


@router.get("/{document_id}/inline")
async def inline_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_document_as_admin(document_id, current_user.id, db, current_user.role in ('admin', 'super_admin'))

    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    file_type = (doc.file_type or "").lower()
    if file_type == "pdf":
        return FileResponse(resolved_path, media_type="application/pdf")

    if file_type == "md":
        from app.services.document_processor.md_parser import MdParser
        parsed = MdParser.parse(resolved_path)
        return HTMLResponse(parsed.get("html", ""))

    if file_type == "txt":
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

    raise HTTPException(status_code=400, detail=f"不支持内联预览此文件类型: {file_type}")


@router.get("/{document_id}/raw")
async def raw_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_user_document(document_id, current_user.id, db)

    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        resolved_path,
        filename=doc.original_filename,
        media_type=_get_file_media_type((doc.file_type or "").lower())
    )


@router.post("/{document_id}/save")
async def save_document_content(
    document_id: UUID,
    payload: DocumentSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_user_document(document_id, current_user.id, db)
    _ensure_document_owner(doc, current_user.id, current_user.role in ('admin', 'super_admin'))

    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_type = (doc.file_type or "").lower()
    if file_type == "txt":
        from app.services.document_processor.txt_parser import TxtParser
        TxtParser.write(payload.content, resolved_path)
    elif file_type == "md":
        from app.services.document_processor.md_parser import MdParser
        MdParser.write(payload.content, resolved_path)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_document_as_admin(document_id, current_user.id, db, current_user.role in ('admin', 'super_admin'))

    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        resolved_path,
        filename=doc.original_filename,
        media_type=_get_file_media_type((doc.file_type or "").lower())
    )


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_user_document(document_id, current_user.id, db)
    return doc


@router.post("/{document_id}/retry-extraction")
async def retry_extraction(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_user_document(document_id, current_user.id, db)

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
        user_id=current_user.id,
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

    # 使用 asyncio.create_task 并发启动任务，通过队列限制并发数
    asyncio.create_task(
        _queued_extract_document_with_task(
            doc.id,
            doc.file_path,
            doc.file_type,
            doc.original_filename,
            task.id,
        )
    )

    return {"message": "重新预处理已启动", "document_id": document_id}


async def _queued_extract_document_with_task(
    doc_id: UUID,
    file_path: str,
    file_type: str,
    original_filename: str,
    task_id: UUID
):
    """通过任务队列执行文档提取（限制并发数）"""
    from app.services.task_queue import enqueue_task

    await enqueue_task(
        auto_extract_document_with_task,
        doc_id,
        file_path,
        file_type,
        original_filename,
        task_id,
        task_name=f"retry_{original_filename}",
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = await _get_user_document(document_id, current_user.id, db)
    _ensure_document_owner(doc, current_user.id, current_user.role in ('admin', 'super_admin'))

    doc_id_str = str(document_id)

    try:
        # 0. 取消正在运行的预处理任务
        try:
            from app.services.task_queue import cancel_task
            cancelled = cancel_task(doc_id_str)
            if cancelled:
                logger.info(f"已取消文档 {doc_id_str} 的预处理任务")
        except Exception as e:
            logger.warning(f"取消任务失败: {e}")

        # 0.5. 删除 template_usage_events 表中的相关记录
        try:
            from app.models.document import TemplateUsageEvent
            await db.execute(
                text("DELETE FROM template_usage_events WHERE template_id = :doc_id OR output_file_id = :doc_id"),
                {"doc_id": document_id}
            )
            logger.info(f"已删除文档 {doc_id_str} 的 template_usage_events 记录")
        except Exception as e:
            logger.warning(f"删除 template_usage_events 记录失败: {e}")

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
