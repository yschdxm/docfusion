import asyncio
import json
import os
from datetime import datetime, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.db.postgres import get_db
from app.models.document import Document
from app.models.user import User
from app.models.user_agently_token import UserAgentlyToken
from app.services.agently_mail_service import agently_mail_service

router = APIRouter()
settings = get_settings()


class OAuthStartResponse(BaseModel):
    """OAuth 授权启动响应"""
    verification_uri: str
    user_code: str
    device_code: str
    expires_in: int


class OAuthPollResponse(BaseModel):
    """OAuth 轮询响应"""
    status: str  # "pending" | "completed" | "expired" | "error"
    email: str | None = None
    error: str | None = None


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
async def mail_status(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取邮件服务状态"""
    try:
        # 先检查用户是否有 token
        token = await agently_mail_service.get_user_token(db, current_user.id)
        if not token:
            return {"available": True, "authorized": False, "email": None, "error": "未授权"}

        me = await agently_mail_service.me(user_token=token)
        return {"available": True, **me}
    except Exception as exc:
        return {"available": False, "authorized": False, "email": None, "error": str(getattr(exc, "detail", exc))}


@router.get("/messages")
async def list_messages(limit: int = 20, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取邮件列表"""
    token = await agently_mail_service.get_user_token(db, current_user.id)
    if not token:
        raise HTTPException(status_code=401, detail="未授权，请先完成 Agently 授权")
    return await agently_mail_service.list_messages(limit=limit, user_token=token)


@router.get("/messages/{message_id}")
async def get_message(message_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取邮件详情"""
    token = await agently_mail_service.get_user_token(db, current_user.id)
    if not token:
        raise HTTPException(status_code=401, detail="未授权，请先完成 Agently 授权")
    return await agently_mail_service.get_message(message_id, user_token=token)


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
    """发送邮件"""
    token = await agently_mail_service.get_user_token(db, current_user.id)
    if not token:
        raise HTTPException(status_code=401, detail="未授权，请先完成 Agently 授权")
    document_attachments = await _resolve_document_attachment_paths(db, current_user, payload.document_ids)
    return await agently_mail_service.send_message(payload.to, payload.subject, payload.body, [*payload.attachments, *document_attachments], user_token=token)


@router.post("/send/confirm")
async def confirm_send_message(payload: MailConfirmSendRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """确认发送邮件"""
    token = await agently_mail_service.get_user_token(db, current_user.id)
    if not token:
        raise HTTPException(status_code=401, detail="未授权，请先完成 Agently 授权")
    document_attachments = await _resolve_document_attachment_paths(db, current_user, payload.document_ids)
    return await agently_mail_service.confirm_send_message(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        attachments=[*payload.attachments, *document_attachments],
        confirmation_token=payload.confirmation_token,
        user_token=token,
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
    """导入邮件附件"""
    token = await agently_mail_service.get_user_token(db, current_user.id)
    if not token:
        raise HTTPException(status_code=401, detail="未授权，请先完成 Agently 授权")
    imported = await agently_mail_service.import_attachment(
        db=db,
        user_id=current_user.id,
        message_id=payload.message_id,
        attachment_id=payload.attachment_id,
        doc_category=payload.doc_category,
        user_token=token,
    )
    await _enqueue_imported_source_documents(db, imported)
    return {"imported": imported, "count": len(imported)}


# ==================== OAuth 授权端点 ====================


@router.get("/auth/status")
async def get_auth_status(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取当前用户的 Agently 授权状态"""
    status = await agently_mail_service.get_user_auth_status(db, current_user.id)
    return status


@router.post("/auth/start")
async def start_auth(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    发起 Agently OAuth 授权（直接调用 OAuth API）

    返回：
    - auth_url: 用户需要访问的授权链接
    - input_code: 用户需要输入的授权码
    - device_code: 设备码，用于轮询
    - expires_in: 过期时间（秒）
    - message: 提示信息
    """
    try:
        # 直接调用 agently 的 OAuth API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://auth.agent.qq.com/oauth/device",
                json={"func": 1},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "agently-cli/1.0.9",
                },
            )
            response.raise_for_status()
            data = response.json()

            auth_url = data.get("browser_url", "")
            input_code = data.get("input_code", "")
            expires_in = data.get("expires_in", 600)

            # 从 poll_url 中提取 device_code
            poll_url = data.get("poll_url", "")
            device_code = ""
            if "device_code=" in poll_url:
                device_code = poll_url.split("device_code=")[1].split("&")[0]

            if not device_code or not auth_url:
                raise HTTPException(status_code=500, detail="无法获取授权信息")

            return {
                "auth_url": auth_url,
                "input_code": input_code,
                "device_code": device_code,
                "expires_in": expires_in,
                "message": "请在浏览器中打开授权链接，输入授权码完成授权",
            }
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Agently OAuth 服务返回错误: {exc.response.status_code}")
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"发起授权失败: {str(exc)}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"发起授权失败: {str(exc)}")


@router.post("/auth/poll")
async def poll_auth(
    device_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    轮询授权状态

    Args:
        device_code: 设备码，从 start_auth 获取

    Returns:
        status: "pending" | "completed" | "expired" | "error"
        email: 授权成功时返回邮箱地址
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        # 直接调用 agently 的 OAuth API 轮询授权状态
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://auth.agent.qq.com/oauth/device",
                params={"func": 2, "device_code": device_code},
                headers={
                    "User-Agent": "agently-cli/1.0.9",
                },
            )
            response.raise_for_status()
            data = response.json()

            # 注意：completed 响应含 access_token/refresh_token/app_secret，不得整体打印
            logger.info(f"[AUTH_POLL] status: {data.get('status', '')}")

            status = data.get("status", "")

            if status == "pending":
                return OAuthPollResponse(status="pending")

            elif status == "completed" or status == "authorized":
                # 授权成功，获取 token
                access_token = data.get("access_token", "")
                refresh_token = data.get("refresh_token", "")
                expires_in = data.get("expires_in")
                email = data.get("email", "")
                # 官方 CLI 刷新 token 时需要把这两个字段作为 client_id/client_secret 上送，必须一并保存
                app_id = data.get("app_id", "")
                app_secret = data.get("app_secret", "")

                logger.info(f"[AUTH_POLL] Authorization completed, email: {email}")

                if access_token:
                    # 保存 token 到数据库
                    try:
                        await agently_mail_service.save_user_token(
                            db=db,
                            user_id=current_user.id,
                            access_token=access_token,
                            refresh_token=refresh_token,
                            expires_in=expires_in,
                            email=email,
                            app_id=app_id,
                            app_secret=app_secret,
                        )
                        logger.info(f"[AUTH_POLL] Token saved for user {current_user.id}")
                    except Exception as save_err:
                        logger.error(f"[AUTH_POLL] Failed to save token: {save_err}")
                        return OAuthPollResponse(
                            status="error",
                            error=f"保存 token 失败: {str(save_err)}",
                        )

                    return OAuthPollResponse(
                        status="completed",
                        email=email,
                    )
                else:
                    return OAuthPollResponse(
                        status="error",
                        error="授权成功但未获取到 token",
                    )

            elif status == "expired":
                return OAuthPollResponse(
                    status="expired",
                    error="授权码已过期，请重新发起授权",
                )

            else:
                # device_code 被并发/迟到的轮询重复消费时，授权服务器会返回错误
                # （如 error_description="internal server error"）。若本用户在授权有效期内
                # 刚刚保存过 token，说明此前已有轮询成功，应按完成处理而不是误报失败。
                saved = await db.execute(
                    select(UserAgentlyToken).where(UserAgentlyToken.user_id == current_user.id)
                )
                saved_record = saved.scalar_one_or_none()
                if (
                    saved_record
                    and saved_record.updated_at
                    and datetime.utcnow() - saved_record.updated_at < timedelta(minutes=10)
                ):
                    logger.warning(
                        f"[AUTH_POLL] duplicate poll after completion, treating as completed "
                        f"(server said: {data.get('error') or data.get('err_code')})"
                    )
                    return OAuthPollResponse(status="completed", email=saved_record.email)

                logger.warning(f"[AUTH_POLL] authorization server error: {data.get('error') or data.get('err_code')}")
                return OAuthPollResponse(
                    status="error",
                    error="授权失败，请重新发起授权",
                )

    except httpx.HTTPStatusError as exc:
        logger.error(f"[AUTH_POLL] HTTP error: {exc.response.status_code}")
        return OAuthPollResponse(
            status="error",
            error=f"Agently OAuth 服务返回错误: {exc.response.status_code}",
        )
    except Exception as exc:
        logger.error(f"[AUTH_POLL] Exception: {exc}", exc_info=True)
        return OAuthPollResponse(
            status="error",
            error=str(exc),
        )


@router.post("/auth/logout")
async def logout_auth(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """取消 Agently 授权"""
    try:
        # 获取用户的 token
        token = await agently_mail_service.get_user_token(db, current_user.id)

        # 如果有 token，调用 agently 的 logout 端点
        if token:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await client.post(
                        settings.AGENTLY_OAUTH_LOGOUT_URL,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                    )
            except Exception:
                # 即使 logout 失败，也删除本地 token
                pass

        # 删除本地存储的 token
        deleted = await agently_mail_service.delete_user_token(db, current_user.id)
        return {"success": deleted, "message": "已取消授权" if deleted else "未找到授权记录"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"取消授权失败: {str(exc)}")
