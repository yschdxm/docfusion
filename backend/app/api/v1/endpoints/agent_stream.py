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
from app.agent.agents.document_agent import create_document_agent
from app.agent.core.task_manager import task_manager, Task
from app.agent.core import pending_actions, message_dedup
from app.core.json_utils import local_iso
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
    auto_review: bool = Field(True, description="AI自动复核开关：False 时 dry_run 结果需用户确认后才执行写入")
    action_response: Optional[dict] = Field(
        None,
        description="确认卡片响应：{\"action_id\": \"...\", \"decision\": \"confirm\"}。"
                    "携带时不作为用户消息持久化，转为内部指令驱动 Agent 提交"
    )
    task_id: Optional[str] = Field(None, description="重连时携带的任务ID")
    last_event_id: Optional[int] = Field(None, description="断点续传：已收到的最大事件序号")
    client_message_id: Optional[str] = Field(
        None,
        description="客户端幂等键：一次用户发送生成一次，连接级重试原样携带；"
                    "服务端按 (conversation_id, client_message_id) 去重，防止重试重复建任务"
    )


class ActionCancelRequest(BaseModel):
    """确认卡片取消请求"""
    action_id: str = Field(..., description="待取消的操作ID")
    conversation_id: str = Field(..., description="对话ID")


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
                    elif msg.role == "assistant" and msg.action_data:
                        # 操作卡片（确认/完成）没有文本内容，合成系统记录注入历史，
                        # 否则新 run 的 LLM 看不到之前发生的 dry_run/确认/取消
                        note = _action_card_note(msg.action_data)
                        if note:
                            conversation_history.append({"role": "assistant", "content": note})
                logger.info(f"[API /agent/stream] 加载了 {len(conversation_history)} 条历史消息")
        except Exception as e:
            logger.warning(f"[API /agent/stream] 加载对话历史失败: {e}")

    # 幂等去重：同一 (conversation_id, client_message_id) 已创建过任务 → 转为订阅回放，
    # 绝不二次执行（前端连接级重试在 task_id 未建立时会以"新任务"重发同一消息）
    if request.conversation_id and request.client_message_id:
        dup_task_id = message_dedup.lookup(request.conversation_id, request.client_message_id)
        if dup_task_id:
            dup_task = await task_manager.get_task(dup_task_id)
            if dup_task:
                logger.warning(
                    f"[API /agent/stream] 幂等去重命中，转为订阅 | "
                    f"cmid={request.client_message_id[:8]} | task_id={dup_task_id[:8]}"
                )
                return _subscribe_response(dup_task, after_seq=0)
            # 极小概率窗口：去重记录还在但任务已被清理 → 任务已执行过，拒绝重复执行
            logger.warning(
                f"[API /agent/stream] 幂等去重命中但任务已清理，拒绝重复执行 | "
                f"cmid={request.client_message_id[:8]} | task_id={dup_task_id[:8]}"
            )
            return _error_response("该请求已处理过，请刷新查看历史记录")

    # 原子查找或创建任务（防止双击/并发创建重复任务）
    task, created = await task_manager.get_running_or_create(request.conversation_id)
    if not created:
        # 该对话已有运行中任务 → 转为重连
        logger.warning(f"[API /agent/stream] 该对话已有运行中任务，转为重连 | conv={request.conversation_id} | task_id={task.task_id[:8]}")
        return _subscribe_response(task, after_seq=0)

    if request.conversation_id and request.client_message_id:
        message_dedup.register(request.conversation_id, request.client_message_id, task.task_id)

    # 确认卡片响应：转为内部指令，不作为用户消息持久化
    effective_message = request.message
    direct_commit_action_id: Optional[str] = None
    if request.action_response and request.action_response.get("decision") == "confirm":
        direct_commit_action_id = request.action_response.get("action_id", "")
        if not pending_actions.get(direct_commit_action_id):
            return _error_response("该操作已过期或不存在，请重新发起填写")
        await _update_action_card_status(request.conversation_id, direct_commit_action_id, "confirmed")
        logger.info(f"[API /agent/stream] 确认卡片已确认 | action_id={direct_commit_action_id}")
    else:
        # 文字确认拦截：用户手打"确认"且该对话有待确认操作 → 同样走直接提交
        if (request.message.strip().rstrip("。！!~～") in _CONFIRM_PHRASES
                and request.conversation_id):
            latest = pending_actions.latest_pending(request.conversation_id)
            if latest:
                direct_commit_action_id = latest[0]
                logger.info(f"[API /agent/stream] 文字确认拦截 → 直接提交 | action_id={direct_commit_action_id}")
                await _update_action_card_status(request.conversation_id, direct_commit_action_id, "confirmed")

        if request.conversation_id and request.message:
            # 后端统一持久化：保存用户消息
            await save_message(request.conversation_id, "user", request.message)

    # 创建 agent 并启动任务（supervisor 保证终态事件恰好一次 + finish）
    if direct_commit_action_id:
        # 确认路径：服务端直接执行 commit，不经过 LLM（dry_run 已校验、参数已暂存）
        persistence = AgentPersistence(request.conversation_id)
        commit_coro = _run_confirmed_commit(
            task, direct_commit_action_id,
            user_id=str(current_user.id),
            conversation_id=request.conversation_id,
        )
        task_manager.start(task, commit_coro, persistence)
        logger.info(f"[API /agent/stream] 直接提交任务已启动 | task_id={task.task_id[:8]} | action_id={direct_commit_action_id}")
        return _subscribe_response(task, after_seq=0)

    agent = create_document_agent()
    persistence = AgentPersistence(request.conversation_id)
    agent_coro = agent.run(
        message=effective_message,
        file_ids=request.file_ids,
        template_id=request.template_id,
        conversation_history=conversation_history,
        event_log=task.event_log,
        user_id=str(current_user.id),
        cancel_event=task.cancel_event,
        user_selected_model=current_user.selected_model,
        db=None,  # chat_completion 会自己创建 db session
        conversation_id=request.conversation_id,
        auto_review=request.auto_review,
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
        "created_at": local_iso(task.created_at),
        "finished_at": local_iso(task.finished_at),
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


# 文字确认拦截用的确认短语（用户手打这些词且有待确认操作时，直接执行提交）
_CONFIRM_PHRASES = {"确认", "确认提交", "确认执行", "确认写入", "好", "好的", "可以", "是的", "执行", "提交", "ok", "OK", "yes"}


async def _run_confirmed_commit(task: Task, action_id: str, user_id: str,
                                conversation_id: Optional[str]) -> None:
    """确认后的直接提交：不经过 LLM，按暂存参数执行 commit 并推送事件

    dry_run 已完成校验、参数已服务端暂存，commit 是纯确定性操作，
    让 LLM 再经一手只会引入不确定性（丢参数/重读文档/重复提交）。
    """
    from uuid import uuid4

    from app.agent.base.tool import ToolContext
    from app.agent.core.executor import ToolExecutor
    from app.agent.core.registry import ToolRegistry
    from app.agent.tools import FillFormTool, FillTableExecuteTool

    stream = task.event_log
    entry = pending_actions.get(action_id)
    if not entry:
        await stream.emit_failed("待确认操作已过期，请重新发起填写")
        return

    tool_name = entry.get("tool", "fill_table_execute")
    registry = ToolRegistry()
    registry.register(FillTableExecuteTool())
    registry.register(FillFormTool())
    executor = ToolExecutor(registry)

    context = ToolContext(
        session_id=f"confirm_{action_id}",
        user_id=user_id,
        metadata={
            "run_id": uuid4().hex,  # 新一轮 run：版本化按新 run 处理
            "conversation_id": conversation_id,
            "auto_review": False,
            "cancel_event": task.cancel_event,
        },
    )
    commit_params = {"mode": "commit", "confirm_action_id": action_id}

    # 显式开启一个步骤并设 step_id：tool_call/tool_result 据此关联到同一步骤。
    # 不设的话两事件 step_id 都是 None，前端各自兜底成不同时间戳 id，
    # tool_call 建的步骤（50%）永远等不到 tool_result（在另一个 id 上设 100%）。
    step_id = f"confirm_commit_{action_id[:12]}"
    await stream.emit_step_start(step_id, f"确认写入 {tool_name}", "按已确认参数执行写入")
    await stream.emit_tool_call(tool_name, commit_params)
    result = await executor.execute(
        tool_name=tool_name, tool_params=commit_params, context=context, max_retries=1
    )

    if result.success:
        data = result.data if isinstance(result.data, dict) else {"data": str(result.data)}
        await stream.emit_tool_result(
            tool_name=tool_name, result=data, execution_time_ms=result.execution_time_ms
        )
        await stream.emit_step_end(step_id, "写入完成")
        # 多表分别确认场景：本次确认从模板产出了输出文件，把同会话同模板的其它
        # 待确认操作改指到该输出文档——后续确认写入同一文件（版本叠加）而非各自新建
        output_file_id = data.get("output_file_id")
        template_id = entry.get("params", {}).get("template_id", "")
        if output_file_id and template_id:
            pending_actions.retarget_pending(conversation_id, template_id, output_file_id)
        message = data.get("message", "写入完成")
        if data.get("download_url"):
            message += f"\n\n[点击下载文档]({data['download_url']})"
        await stream.emit_completed(message, result_data=data)
    else:
        await stream.emit_tool_error(tool_name, result.error or "写入失败")
        await stream.emit_step_end(step_id, f"写入失败: {result.error}")
        await stream.emit_failed(result.error or "写入失败")


@router.post("/action/cancel")
async def cancel_pending_action(
    request: ActionCancelRequest,
    current_user: User = Depends(get_current_user),
):
    """取消待确认的写入操作：标记 pending action 终态 + 更新卡片消息状态（不启动 Agent）"""
    resolved = pending_actions.resolve(request.action_id, "cancelled")
    # 即便暂存已过期，也尝试更新卡片消息状态，保证 UI 一致性
    await _update_action_card_status(request.conversation_id, request.action_id, "cancelled")
    logger.info(f"[API /agent/action/cancel] action_id={request.action_id} | resolved={resolved}")
    return {"status": "ok", "was_pending": resolved}


def _action_card_note(action_data: dict) -> str:
    """把操作卡片转为注入对话历史的系统记录（让新 run 的 LLM 知道之前发生了什么）"""
    if not isinstance(action_data, dict):
        return ""
    action_type = action_data.get("action_type")
    if action_type == "confirm_fill":
        status = action_data.get("status")
        summary = action_data.get("summary", "")
        if status == "pending":
            return (
                f"[系统记录] 此前执行过一次写入前校验（dry_run）：{summary}；"
                "该操作仍在等待用户在界面上点击确认/取消，用户尚未处理。"
                "严禁自行调用 commit；若用户发来新指令，按新指令重新 dry_run。"
            )
        if status == "confirmed":
            return (
                f"[系统记录] 此前执行过一次写入前校验（dry_run）：{summary}；"
                "用户已确认，写入已由服务端执行完毕，无需再次执行。"
            )
        if status == "cancelled":
            return (
                f"[系统记录] 此前执行过一次写入前校验（dry_run）：{summary}；"
                "该次写入已被用户取消，如用户再次要求填写，需要重新走 plan → dry_run 流程。"
            )
        return f"[系统记录] 此前执行过一次写入前校验（dry_run）：{summary}。"
    if action_type == "completed" and action_data.get("filled_file_url"):
        return f"[系统记录] 此前已完成一次文档写入，输出文件: {action_data['filled_file_url']}。"
    return ""


async def _update_action_card_status(conversation_id: Optional[str], action_id: str, status: str) -> None:
    """更新确认卡片消息的 action_data.status（ confirmed / cancelled ）"""
    if not conversation_id or not action_id:
        return
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .where(Message.action_data["action_id"].as_string() == action_id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            msg = result.scalar_one_or_none()
            if not msg or not msg.action_data:
                return
            updated = {**msg.action_data, "status": status}
            msg.action_data = updated
            await db.commit()
    except Exception as e:
        logger.warning(f"[API] 更新卡片状态失败 | action_id={action_id} | error={e}")

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
    """任务不存在的响应（stale_task 标记供前端识别为陈旧任务，静默收尾而非报错）"""
    async def gen():
        yield AgentEvent(
            event_type=AgentEventType.FAILED,
            data={"error": "任务不存在或已过期", "stale_task": True},
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
