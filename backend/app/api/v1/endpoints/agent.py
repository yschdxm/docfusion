from fastapi import APIRouter, Depends
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.postgres import get_db
from app.services.llm_service import llm_service
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str
    file_ids: List[UUID] = []
    template_id: Optional[UUID] = None
    conversation_history: List[Dict[str, str]] = []
    action_confirmed: bool = False
    action_id: Optional[str] = None
    task_id: Optional[str] = None


class AgentAction(BaseModel):
    action_id: str
    action_type: str
    title: str
    description: str
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None
    filled_file_url: Optional[str] = None
    filled_file_id: Optional[str] = None


class AgentChatResponse(BaseModel):
    message: str
    action: Optional[AgentAction] = None


class GenerateTitleRequest(BaseModel):
    message: str


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    智能体对话接口（兼容旧版本）

    已统一使用 /agent/stream 端点，建议迁移到流式接口获取完整体验。
    """
    logger.info(f"[AgentChat] 收到请求: {request.message[:50]}...")

    return AgentChatResponse(
        message=f"💡 提示：请使用新的 /agent/stream 端点体验实时Agent思考过程！\n\n"
               f"您的消息：{request.message[:100]}{'...' if len(request.message) > 100 else ''}"
    )


@router.post("/generate-title")
async def generate_title(request: GenerateTitleRequest):
    """轻量接口：根据用户消息生成对话标题"""
    try:
        prompt = f"请用10个字以内总结以下问题的标题，只返回标题内容，不要返回其他任何内容。\n问题：{request.message[:50]}"
        title = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=65536
        )
        return {"title": title.strip()[:10]}
    except Exception as e:
        logger.error(f"生成标题失败: {e}")
        return {"title": "新对话"}
