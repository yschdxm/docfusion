from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, or_
from datetime import datetime
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.db.postgres import get_db
from app.models.document import Conversation, Message
from app.models.user import User

settings = get_settings()
router = APIRouter()


def _user_conv_filter(user_id):
    """构建用户对话过滤条件"""
    if settings.INCLUDE_ORPHAN_DATA:
        return or_(Conversation.user_id == user_id, Conversation.user_id.is_(None))
    return Conversation.user_id == user_id


async def _get_user_conversation(conversation_id: str, user_id, db: AsyncSession) -> Conversation:
    """获取对话并确保属于当前用户"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            _user_conv_filter(user_id)
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


class ConversationCreate(BaseModel):
    id: str
    title: str = "新对话"
    file_ids: List[str] = []
    template_id: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    file_ids: Optional[List[str]] = None
    template_id: Optional[str] = None


class MessageCreate(BaseModel):
    role: str
    content: str
    action_data: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    file_ids: List[str]
    template_id: Optional[str]
    created_at: str
    updated_at: str
    messages: List[Dict[str, Any]] = []


@router.get("/", response_model=List[Dict[str, Any]])
async def list_conversations(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取对话列表"""
    result = await db.execute(
        select(Conversation)
        .where(_user_conv_filter(current_user.id))
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    conversations = result.scalars().all()

    conv_list = []
    for conv in conversations:
        # 获取最后一条消息
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()

        conv_list.append({
            "id": conv.id,
            "title": conv.title,
            "file_ids": conv.file_ids or [],
            "template_id": conv.template_id,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            "last_message": last_msg.content[:50] if last_msg else None
        })

    return conv_list


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取单个对话及其消息"""
    conv = await _get_user_conversation(conversation_id, current_user.id, db)

    # 获取所有消息
    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    )
    messages = msg_result.scalars().all()

    return {
        "id": conv.id,
        "title": conv.title,
        "file_ids": conv.file_ids or [],
        "template_id": conv.template_id,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "action_data": msg.action_data,
                "steps": msg.steps,
                "timestamp": int(msg.created_at.timestamp() * 1000) if msg.created_at else None
            }
            for msg in messages
        ]
    }


@router.post("/", response_model=Dict[str, Any])
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建新对话"""
    conv = Conversation(
        id=data.id,
        user_id=current_user.id,
        title=data.title,
        file_ids=data.file_ids,
        template_id=data.template_id
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return {
        "id": conv.id,
        "title": conv.title,
        "file_ids": conv.file_ids,
        "template_id": conv.template_id,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat()
    }


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新对话"""
    conv = await _get_user_conversation(conversation_id, current_user.id, db)

    if data.title is not None:
        conv.title = data.title
    if data.file_ids is not None:
        conv.file_ids = data.file_ids
    if data.template_id is not None:
        conv.template_id = data.template_id

    conv.updated_at = datetime.utcnow()
    await db.commit()

    return {"message": "Updated"}


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除对话及其所有消息"""
    conv = await _get_user_conversation(conversation_id, current_user.id, db)

    await db.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await db.execute(
        delete(Conversation).where(Conversation.id == conversation_id)
    )
    await db.commit()

    return {"message": "Deleted"}


@router.post("/{conversation_id}/messages")
async def add_message(
    conversation_id: str,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """添加消息到对话"""
    # 检查对话是否存在且属于当前用户
    conv = await _get_user_conversation(conversation_id, current_user.id, db)

    msg = Message(
        conversation_id=conversation_id,
        role=data.role,
        content=data.content,
        action_data=data.action_data,
        steps=data.steps
    )
    db.add(msg)

    # 更新对话的更新时间
    conv.updated_at = datetime.utcnow()

    await db.commit()

    return {"message": "Message added", "id": msg.id}


@router.put("/{conversation_id}/messages/{message_id}")
async def update_message(
    conversation_id: str,
    message_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新消息"""
    # 验证对话归属
    await _get_user_conversation(conversation_id, current_user.id, db)

    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.content = data.content
    if data.action_data is not None:
        msg.action_data = data.action_data
    if data.steps is not None:
        msg.steps = data.steps

    await db.commit()

    return {"message": "Message updated"}
