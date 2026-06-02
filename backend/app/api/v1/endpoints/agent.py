from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from uuid import UUID
from app.core.deps import get_current_user
from app.db.postgres import get_db
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


@router.get("/models")
async def get_available_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取可用模型列表（所有用户可访问）"""
    from app.services.config_service import config_service
    import json as json_lib

    configs = await config_service.get_all(db)
    config_map = {c.key: c.value for c in configs}

    models = []

    # 从新的供应商JSON格式解析
    providers_json = config_map.get('llm_providers', '')
    if providers_json:
        try:
            providers = json_lib.loads(providers_json)
            for provider in providers:
                provider_id = provider.get('id', '')
                provider_name = provider.get('name', '')
                # 查找该供应商的所有模型
                prefix = f'llm_{provider_id}_'
                for key in config_map:
                    if key.startswith(prefix) and key.endswith('_max_context_tokens'):
                        model_name = key[len(prefix):-len('_max_context_tokens')]
                        if model_name:
                            models.append({
                                "id": model_name,
                                "name": model_name,
                                "provider": provider_name,
                            })
        except json_lib.JSONDecodeError:
            pass

    # 获取用户选择的模型（如果用户未选择过则为空）
    selected_model = current_user.selected_model or ""

    return {"models": models, "current": selected_model}


@router.post("/model/switch")
async def switch_model(
    request: SwitchModelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """切换模型（从数据库配置中加载）"""
    try:
        from app.services.config_service import config_service
        import json as json_lib

        model_name = request.provider  # provider参数现在是模型名称

        # 从数据库获取所有配置
        configs = await config_service.get_all(db)
        config_map = {c.key: c.value for c in configs}

        # 从新的供应商JSON格式中查找模型
        providers_json = config_map.get('llm_providers', '')
        if not providers_json:
            return {"success": False, "error": "未配置任何LLM供应商"}

        providers = json_lib.loads(providers_json)

        found = False
        for provider in providers:
            provider_id = provider.get('id', '')
            api_key = provider.get('api_key', '')
            base_url = provider.get('base_url', '')

            # 检查该供应商下是否有这个模型
            ctx_key = f'llm_{provider_id}_{model_name}_max_context_tokens'
            out_key = f'llm_{provider_id}_{model_name}_max_output_tokens'

            if ctx_key in config_map and out_key in config_map:
                max_context_tokens = config_map.get(ctx_key, '')
                max_output_tokens = config_map.get(out_key, '')

                if not max_context_tokens or not max_output_tokens:
                    continue

                if not api_key or not base_url:
                    return {"success": False, "error": f"供应商 {provider.get('name', '')} 的 API Key 或 Base URL 未配置"}

                # 更新配置
                result = llm_service.update_config(
                    api_key=api_key,
                    base_url=base_url,
                    model=model_name,
                    max_context_tokens=int(max_context_tokens),
                    max_output_tokens=int(max_output_tokens)
                )

                found = True
                break

        if not found:
            return {"success": False, "error": f"未找到模型 {model_name} 的配置"}

        # 保存用户选择到数据库
        current_user.selected_model = model_name
        await db.commit()

        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e)}
