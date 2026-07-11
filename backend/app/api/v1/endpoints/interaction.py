"""
交互控制器 - 处理前端交互请求

负责：
- 右键菜单操作
- 侧边栏对话
- 单元格交互
- 工具栏操作
- 审批响应
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import logging

from app.agent.base.tool import ToolContext
from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class ContextMenuActionRequest(BaseModel):
    """右键菜单操作请求"""
    file_id: str
    action: str  # "rewrite", "translate", "summarize", "extract", "format", "custom"
    selected_text: str
    selection_range: Optional[Dict[str, Any]] = None
    custom_instruction: Optional[str] = None


class ChatMessageRequest(BaseModel):
    """对话消息请求"""
    message: str
    file_ids: list[str] = []
    template_id: Optional[str] = None
    session_id: Optional[str] = None


class CellActionRequest(BaseModel):
    """单元格操作请求"""
    file_id: str
    sheet_name: Optional[str] = None
    row: int
    col: int
    action: str  # "auto_fill", "extract", "query", "custom"
    custom_instruction: Optional[str] = None


class ToolbarActionRequest(BaseModel):
    """工具栏操作请求"""
    file_id: Optional[str] = None
    action: str  # "assistant", "fill", "search", "settings"
    params: Optional[Dict[str, Any]] = None


class ApprovalRequestModel(BaseModel):
    """审批请求模型"""
    request_id: str
    approved: bool
    modified_params: Optional[Dict[str, Any]] = None
    user_message: Optional[str] = None


@router.post("/context-menu")
async def handle_context_menu_action(
    request: ContextMenuActionRequest,
    current_user: User = Depends(get_current_user)
):
    """处理右键菜单操作"""
    try:
        # 构建任务描述
        task_description = _build_context_menu_task(request)

        # 创建工具上下文
        context = ToolContext(
            session_id=f"ctx_menu_{request.file_id}",
            user_id=str(current_user.id),
            file_ids=[request.file_id]
        )

        # 获取编排器
        from app.agent.core.initialization import get_orchestrator
        orchestrator = get_orchestrator()

        # 分发到合适的Agent
        result = await orchestrator.dispatch(
            user_message=task_description,
            context=context,
            preferred_agent="editor"
        )

        return {"success": True, "result": result}

    except Exception as e:
        logger.exception(f"右键菜单操作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def handle_chat_message(
    request: ChatMessageRequest,
    current_user: User = Depends(get_current_user)
):
    """处理侧边栏对话"""
    try:
        # 创建工具上下文
        context = ToolContext(
            session_id=request.session_id or f"chat_{current_user.id}",
            user_id=str(current_user.id),
            file_ids=request.file_ids,
            template_id=request.template_id
        )

        # 获取编排器
        from app.agent.core.initialization import get_orchestrator
        orchestrator = get_orchestrator()

        # 分发请求
        result = await orchestrator.dispatch(
            user_message=request.message,
            context=context
        )

        return {"success": True, "result": result}

    except Exception as e:
        logger.exception(f"对话处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cell")
async def handle_cell_action(
    request: CellActionRequest,
    current_user: User = Depends(get_current_user)
):
    """处理单元格交互"""
    try:
        # 构建任务描述
        task_description = _build_cell_task(request)

        # 创建工具上下文
        context = ToolContext(
            session_id=f"cell_{request.file_id}",
            user_id=str(current_user.id),
            file_ids=[request.file_id]
        )

        # 获取编排器
        from app.agent.core.initialization import get_orchestrator
        orchestrator = get_orchestrator()

        # 分发到表格Agent
        result = await orchestrator.dispatch(
            user_message=task_description,
            context=context,
            preferred_agent="table"
        )

        return {"success": True, "result": result}

    except Exception as e:
        logger.exception(f"单元格操作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toolbar")
async def handle_toolbar_action(
    request: ToolbarActionRequest,
    current_user: User = Depends(get_current_user)
):
    """处理工具栏操作"""
    try:
        # 创建工具上下文
        context = ToolContext(
            session_id=f"toolbar_{current_user.id}",
            user_id=str(current_user.id),
            file_ids=[request.file_id] if request.file_id else []
        )

        # 获取编排器
        from app.agent.core.initialization import get_orchestrator
        orchestrator = get_orchestrator()

        # 根据操作类型分发
        if request.action == "assistant":
            # 打开侧边栏，等待用户输入
            return {"success": True, "action": "open_sidebar"}
        elif request.action == "fill":
            result = await orchestrator.dispatch(
                user_message="填写表格",
                context=context,
                preferred_agent="table"
            )
            return {"success": True, "result": result}
        elif request.action == "search":
            result = await orchestrator.dispatch(
                user_message="搜索文档",
                context=context,
                preferred_agent="search"
            )
            return {"success": True, "result": result}
        else:
            return {"success": True, "action": request.action}

    except Exception as e:
        logger.exception(f"工具栏操作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve")
async def handle_approval(
    request: ApprovalRequestModel,
    current_user: User = Depends(get_current_user)
):
    """处理审批响应"""
    try:
        # 这里需要实现审批逻辑
        # 暂时返回成功
        return {
            "success": True,
            "request_id": request.request_id,
            "approved": request.approved
        }

    except Exception as e:
        logger.exception(f"审批处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/{file_id}")
async def get_editor_context(
    file_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取文档编辑器上下文"""
    try:
        # 查询文档信息
        from app.db.postgres import async_session
        from app.models.document import Document
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(Document).where(Document.id == file_id)
            )
            doc = result.scalar_one_or_none()

            if not doc:
                raise HTTPException(status_code=404, detail="文档不存在")

            return {
                "success": True,
                "context": {
                    "file_id": str(doc.id),
                    "file_type": doc.file_type,
                    "filename": doc.original_filename,
                    "doc_category": doc.doc_category,
                    "status": doc.status
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取文档上下文失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _build_context_menu_task(request: ContextMenuActionRequest) -> str:
    """构建右键菜单任务描述"""
    action_map = {
        "rewrite": "改写选中的文本",
        "translate": "翻译选中的文本",
        "summarize": "总结选中的内容",
        "extract": "提取选中的信息",
        "format": "调整选中的格式",
        "custom": request.custom_instruction or "处理选中的内容"
    }

    action_desc = action_map.get(request.action, "处理选中的内容")
    return f"{action_desc}：\n{request.selected_text[:200]}"


def _build_cell_task(request: CellActionRequest) -> str:
    """构建单元格任务描述"""
    action_map = {
        "auto_fill": f"自动填充单元格 ({request.row}, {request.col})",
        "extract": f"从文档提取数据填充单元格 ({request.row}, {request.col})",
        "query": f"从数据库查询数据填充单元格 ({request.row}, {request.col})",
        "custom": request.custom_instruction or f"处理单元格 ({request.row}, {request.col})"
    }

    return action_map.get(request.action, f"处理单元格 ({request.row}, {request.col})")
