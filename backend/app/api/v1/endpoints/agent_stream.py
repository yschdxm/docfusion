"""
流式Agent API端点

提供SSE(Server-Sent Events)格式的流式输出，实时展示Agent执行过程。

架构（事件溯源 + 发布/订阅）：
- 每个任务一份 TaskEventLog（有序事件日志，事件带单调递增 seq）
- HTTP 连接只是日志的一个订阅者：断开不影响任务，重连通过 after_seq 断点续传
- 消息持久化由 AgentPersistence 订阅者独立承担，与 HTTP 连接生命周期无关

协议：
- SSE 标准三字段：id: <seq> / event: <event_type> / data: <json>
- task_id 通过响应头 X-Task-Id 返回（新任务与重连一致）
- 重连续传：请求头 Last-Event-ID 或请求体 last_event_id
- 任务状态查询：GET /agent/tasks/{task_id}/status
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import logging

from app.agent.core.stream import AgentEvent, AgentEventType
from app.agent.agents.general_agent import create_general_agent
from app.agent.core.task_manager import task_manager, Task
from app.core.deps import get_current_user
from app.core.sse import SSE_HEADERS, SSE_KEEPALIVE
from app.db.postgres import async_session
from app.models.document import Message, Conversation
from app.models.user import User
from app.services.agent_persistence import AgentPersistence, save_message
from sqlalchemy import select


logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 请求模型
# ============================================================

class AgentStreamRequest(BaseModel):
    """流式Agent请求"""
    message: str = Field("", description="用户消息")
    file_ids: List[str] = Field(default_factory=list, description="源文档ID列表")
    template_id: Optional[str] = Field(None, description="模板文档ID")
    conversation_id: Optional[str] = Field(None, description="对话ID")
    task_type: str = Field("auto", description="任务类型: auto/fill_table/query/operation")
    task_id: Optional[str] = Field(None, description="重连时携带的任务ID")
    last_event_id: Optional[int] = Field(None, description="断点续传：已收到的最大事件序号")


# ============================================================
# API 端点
# ============================================================

@router.post("/stream")
async def agent_stream(
    request: AgentStreamRequest,
    current_user: User = Depends(get_current_user),
    last_event_id_header: Optional[int] = Header(None, alias="Last-Event-ID"),
):
    """
    流式Agent对话接口

    使用SSE(Server-Sent Events)格式实时推送Agent执行过程。
    支持断线重连：通过 task_id + Last-Event-ID 接入已有任务并从断点续传，不重启。
    """
    after_seq = request.last_event_id or last_event_id_header or 0

    # === 情况1: 重连 — 接入已有任务 ===
    if request.task_id:
        logger.info(f"[API /agent/stream] 重连请求 | task_id={request.task_id[:8]} | after_seq={after_seq}")
        task = await task_manager.get_task(request.task_id)
        if not task:
            return _task_not_found_response()
        return _subscribe_response(task, after_seq=after_seq)

    # === 情况2: 新任务 ===
    logger.info("=" * 70)
    logger.info("[API /agent/stream] 收到新任务请求")
    logger.info(f"[API /agent/stream] 消息: {request.message[:100]}..." if len(request.message) > 100 else f"[API /agent/stream] 消息: {request.message}")
    logger.info(f"[API /agent/stream] 文件数: {len(request.file_ids)} | 模板ID: {request.template_id} | 对话ID: {request.conversation_id}")

    # 检查用户是否已选择模型（前端已检查，这里做兜底）
    if not current_user.selected_model:
        logger.warning(f"[API /agent/stream] 用户未选择模型: user_id={current_user.id}")
        return _error_response("请先在左下角选择一个模型")

    # 加载对话历史
    conversation_history = []
    if request.conversation_id:
        try:
            async with async_session() as db:
                # 校验对话归属
                conv_result = await db.execute(
                    select(Conversation).where(Conversation.id == request.conversation_id)
                )
                conv = conv_result.scalar_one_or_none()
                if conv and conv.user_id and conv.user_id != current_user.id:
                    return _error_response("无权访问该对话")

                msg_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == request.conversation_id)
                    .order_by(Message.created_at.asc())
                    .limit(20)
                )
                messages = msg_result.scalars().all()
                for msg in messages:
                    if msg.role in ("user", "assistant") and msg.content:
                        conversation_history.append({
                            "role": msg.role,
                            "content": msg.content
                        })
                logger.info(f"[API /agent/stream] 加载了 {len(conversation_history)} 条历史消息")
        except Exception as e:
            logger.warning(f"[API /agent/stream] 加载对话历史失败: {e}")

    # 原子查找或创建任务（防止双击/并发创建重复任务）
    task, created = await task_manager.get_running_or_create(request.conversation_id)
    if not created:
        # 该对话已有运行中任务 → 转为重连
        logger.warning(f"[API /agent/stream] 该对话已有运行中任务，转为重连 | conv={request.conversation_id} | task_id={task.task_id[:8]}")
        return _subscribe_response(task, after_seq=0)

    # 后端统一持久化：保存用户消息
    if request.conversation_id and request.message:
        await save_message(request.conversation_id, "user", request.message)

    # 创建 agent 并启动任务（supervisor 保证终态事件恰好一次 + finish）
    agent = create_general_agent(stream_manager_provider=lambda: task.event_log)
    persistence = AgentPersistence(request.conversation_id)
    agent_coro = agent.run(
        message=request.message,
        file_ids=request.file_ids,
        template_id=request.template_id,
        conversation_history=conversation_history,
        event_log=task.event_log,
        user_id=str(current_user.id),
        cancel_event=task.cancel_event,
        user_selected_model=current_user.selected_model,
        db=None,  # chat_completion 会自己创建 db session
        conversation_id=request.conversation_id,
    )
    task_manager.start(task, agent_coro, persistence)

    logger.info(f"[API /agent/stream] 任务已启动 | task_id={task.task_id[:8]}")
    return _subscribe_response(task, after_seq=0)


@router.get("/tasks/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """查询任务状态（前端用于判断任务死活，替代猜测式兜底）"""
    task = await task_manager.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found", "last_seq": 0}
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "last_seq": task.event_log.last_seq,
        "conversation_id": task.conversation_id,
        "created_at": task.created_at.isoformat(),
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "result": task.result,
    }


@router.delete("/stream/{task_id}")
async def cancel_agent_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """彻底取消任务（用户主动停止）。幂等。"""
    cancelled = await task_manager.cancel(task_id)
    if not cancelled:
        return {"status": "not_found", "message": "任务不存在或已结束"}
    return {"status": "ok"}


# ============================================================
# SSE 响应构造
# ============================================================

def _subscribe_response(task: Task, after_seq: int = 0) -> StreamingResponse:
    """订阅任务事件日志的 SSE 响应

    回放 seq > after_seq 的缓冲事件后接实时流；
    任务已结束时只回放缓冲然后自然结束（终态事件在缓冲中）。
    """
    async def event_source():
        try:
            async for item in task.event_log.subscribe(after_seq=after_seq):
                if item is None:
                    yield SSE_KEEPALIVE
                else:
                    yield item.to_sse_format()
        except Exception as e:
            logger.warning(f"[API /agent/stream] 订阅异常 | task_id={task.task_id[:8]} | error={e}")
        finally:
            logger.info(f"[API /agent/stream] 订阅结束 | task_id={task.task_id[:8]} | after_seq={after_seq}")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, "X-Task-Id": task.task_id},
    )


def _task_not_found_response() -> StreamingResponse:
    """任务不存在的响应"""
    async def gen():
        yield AgentEvent(
            event_type=AgentEventType.FAILED,
            data={"error": "任务不存在或已过期"},
        ).to_sse_format()
    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


def _error_response(error: str) -> StreamingResponse:
    """参数/权限错误的响应（使用标准 FAILED 事件，前端可正常解析）"""
    async def gen():
        yield AgentEvent(
            event_type=AgentEventType.FAILED,
            data={"error": error},
        ).to_sse_format()
    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)
