import asyncio
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.postgres import get_db
from app.models.document import Document
from app.models.user import User
from app.services.agently_mail_service import agently_mail_service

router = APIRouter()


class MailSendRequest(BaseModel):
    to: str = Field(..., description="收件人邮箱")
    subject: str = Field(..., description="主题")
    body: str = Field("", description="正文")
    attachments: list[str] = Field(default_factory=list, description="附件路径列表")
    document_ids: list[UUID] = Field(default_factory=list, description="文档管理中的文件ID列表，将作为邮件附件发送")


class MailConfirmSendRequest(MailSendRequest):
    confirmation_token: str = Field(..., description="第一次发送返回的确认 token")


class MailImportAttachmentRequest(BaseModel):
    message_id: str
    attachment_id: str
    doc_category: str = "source"


@router.get("/status")
async def mail_status(current_user: User = Depends(get_current_user)):
    try:
        me = await agently_mail_service.me()
        return {"available": True, **me}
    except Exception as exc:
        return {"available": False, "authorized": False, "email": None, "error": str(getattr(exc, "detail", exc))}


@router.get("/messages")
async def list_messages(limit: int = 20, current_user: User = Depends(get_current_user)):
    return await agently_mail_service.list_messages(limit=limit)


@router.get("/messages/{message_id}")
async def get_message(message_id: str, current_user: User = Depends(get_current_user)):
    return await agently_mail_service.get_message(message_id)


async def _resolve_document_attachment_paths(db: AsyncSession, current_user: User, document_ids: list[UUID]) -> list[str]:
    if not document_ids:
        return []
    result = await db.execute(select(Document).where(Document.id.in_(document_ids)))
    docs = result.scalars().all()
    found_ids = {doc.id for doc in docs}
    missing_ids = [str(doc_id) for doc_id in document_ids if doc_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"附件文档不存在: {', '.join(missing_ids)}")
    paths: list[str] = []
    for doc in docs:
        if doc.user_id and doc.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=f"无权发送文档附件: {doc.original_filename}")
        if not doc.file_path or not os.path.exists(doc.file_path):
            raise HTTPException(status_code=404, detail=f"附件文件不存在或已丢失: {doc.original_filename}")
        paths.append(doc.file_path)
    return paths


@router.post("/send")
async def send_message(payload: MailSendRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    document_attachments = await _resolve_document_attachment_paths(db, current_user, payload.document_ids)
    return await agently_mail_service.send_message(payload.to, payload.subject, payload.body, [*payload.attachments, *document_attachments])


@router.post("/send/confirm")
async def confirm_send_message(payload: MailConfirmSendRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    document_attachments = await _resolve_document_attachment_paths(db, current_user, payload.document_ids)
    return await agently_mail_service.confirm_send_message(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        attachments=[*payload.attachments, *document_attachments],
        confirmation_token=payload.confirmation_token,
    )


async def _enqueue_imported_source_documents(db: AsyncSession, imported: list[dict]) -> None:
    source_ids: list[UUID] = []
    for item in imported:
        if item.get("doc_category") != "source":
            continue
        try:
            source_ids.append(UUID(str(item.get("id"))))
        except (TypeError, ValueError):
            continue

    if not source_ids:
        return

    result = await db.execute(select(Document).where(Document.id.in_(source_ids)))
    docs = result.scalars().all()

    from app.api.v1.endpoints.documents import _queued_extract_document

    for doc in docs:
        asyncio.create_task(
            _queued_extract_document(
                doc.id,
                doc.file_path,
                doc.file_type,
                doc.original_filename,
                doc.user_id,
            )
        )


@router.post("/attachments/import")
async def import_attachment(
    payload: MailImportAttachmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    imported = await agently_mail_service.import_attachment(
        db=db,
        user_id=current_user.id,
        message_id=payload.message_id,
        attachment_id=payload.attachment_id,
        doc_category=payload.doc_category,
    )
    await _enqueue_imported_source_documents(db, imported)
    return {"imported": imported, "count": len(imported)}
