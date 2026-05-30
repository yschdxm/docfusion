from fastapi import APIRouter, Depends
from typing import List, Optional, Dict, Any
from uuid import UUID
from app.core.deps import get_current_user
from app.models.user import User
from app.services.llm_service import llm_service
from app.core.config import get_settings
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
    current_user: User = Depends(get_current_user)
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


@router.get("/config")
async def get_agent_config(current_user: User = Depends(get_current_user)):
    """返回应用配置"""
    settings = get_settings()
    return {
        "onlyoffice_server_url": settings.ONLYOFFICE_SERVER_URL,
        "backend_public_url": settings.BACKEND_PUBLIC_URL,
    }


@router.post("/generate-title")
async def generate_title(
    request: GenerateTitleRequest,
    current_user: User = Depends(get_current_user)
):
    """轻量接口：根据用户消息生成对话标题"""
    try:
        prompt = f"请用10个字以内总结以下问题的标题，只返回标题内容，不要返回其他任何内容。\n问题：{request.message[:50]}"
        title = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        return {"title": title.strip()[:10]}
    except Exception as e:
        logger.error(f"生成标题失败: {e}")
        return {"title": "新对话"}


class SwitchModelRequest(BaseModel):
    provider: str  # "mimo" 或 "deepseek"


@router.get("/model")
async def get_model_config(current_user: User = Depends(get_current_user)):
    """获取当前模型配置"""
    return llm_service.get_model_info()


@router.post("/model/switch")
async def switch_model(
    request: SwitchModelRequest,
    current_user: User = Depends(get_current_user)
):
    """切换模型提供商"""
    try:
        result = llm_service.switch_model(request.provider)
        return {"success": True, **result}
    except ValueError as e:
        return {"success": False, "error": str(e)}
