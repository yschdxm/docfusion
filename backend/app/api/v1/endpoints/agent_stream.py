"""
流式Agent API端点

提供SSE(Server-Sent Events)格式的流式输出，实时展示Agent执行过程。
支持断线重连：通过 task_id 接入已有任务，不重启。

消息持久化：后端是唯一的持久化权威，所有消息（用户、assistant、steps）统一通过 _save_message 保存。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio
import logging
import json

from app.agent.core.stream import AgentEvent, AgentEventType
from app.agent.agents.general_agent import create_general_agent
from app.agent.core.task_manager import task_manager
from app.db.postgres import async_session
from app.models.document import Message
from sqlalchemy import select


logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# StepAccumulator — 解析 SSE 事件，累积构建 steps 数据
# ============================================================

class StepAccumulator:
    """解析 SSE 事件流，累积构建 steps 数据和 streaming content。

    用于后端持久化时将完整的 steps 信息写入 Message.steps 字段。
    参考前端 agentStreamService._processEvent 的逻辑。
    """

    def __init__(self):
        self._steps: dict[str, dict] = {}       # step_id -> step dict
        self._ordered_ids: list[str] = []
        self._pending_content: str = ""          # content_chunk 累积
        # 子 agent 隔离状态（参考前端 _isChildAgentEvent / _handleChildEvent）
        self._current_agent_name: Optional[str] = None
        self._agent_parent_step_id: Optional[str] = None

    def _is_child_agent_event(self, data: dict) -> bool:
        """判断事件是否来自子 agent"""
        if data.get("is_delegation_end"):
            return False
        return bool(data.get("agent_name") and self._current_agent_name and data["agent_name"] == self._current_agent_name)

    def _get_parent_step(self) -> Optional[dict]:
        """获取当前委派的父步骤"""
        if self._agent_parent_step_id:
            return self._steps.get(self._agent_parent_step_id)
        return None

    def _find_or_create_child_step(self, parent: dict, sid: str, step_type: str, name: str, description: str) -> dict:
        """在父步骤的 children 中查找或创建子步骤"""
        children = parent.setdefault("children", [])
        for child in children:
            if child.get("id") == sid:
                return child
        child = {"id": sid, "type": step_type, "name": name, "description": description, "status": "running", "progress": 0}
        children.append(child)
        return child

    def _handle_child_event(self, event_type: str, data: dict, step_id: Optional[str] = None):
        """处理子 agent 的事件，嵌入到父步骤的 children 中"""
        parent = self._get_parent_step()
        if not parent:
            return
        sid = step_id or f"child_step_{len(parent.get('children', []))}"

        if event_type == "step_start":
            step_type = self._infer_type(data.get("step_name", ""))
            self._find_or_create_child_step(parent, sid, step_type, data.get("step_name", "步骤"), data.get("description", ""))

        elif event_type == "step_progress":
            for child in parent.get("children", []):
                if child.get("id") == sid:
                    child["progress"] = data.get("progress", 0)
                    break

        elif event_type == "step_end":
            for child in parent.get("children", []):
                if child.get("id") == sid:
                    child["status"] = "completed"
                    child["progress"] = 100
                    break

        elif event_type == "thinking_start":
            child = self._find_or_create_child_step(parent, sid, "thinking", data.get("message", "思考中"), "Agent正在分析任务")
            child["status"] = "running"
            child.setdefault("thinkingContent", "")

        elif event_type == "thinking_chunk":
            child = self._find_or_create_child_step(parent, sid, "thinking", "思考中", "Agent正在分析任务")
            child["thinkingContent"] = child.get("thinkingContent", "") + (data.get("content", "") or "")

        elif event_type == "thinking_end":
            for child in parent.get("children", []):
                if child.get("id") == sid:
                    child["status"] = "completed"
                    child["progress"] = 100
                    child["name"] = "思考完成"
                    break

        elif event_type == "tool_call":
            child = self._find_or_create_child_step(parent, sid, "tool_call", f"调用 {data.get('tool_name', '')}", f"执行工具: {data.get('tool_name', '')}")
            child["toolName"] = data.get("tool_name")
            child["toolParams"] = data.get("parameters")

        elif event_type == "tool_result":
            for child in parent.get("children", []):
                if child.get("id") == sid:
                    child["status"] = "completed"
                    child["progress"] = 100
                    child["toolResult"] = data.get("result")
                    break

        elif event_type == "tool_error":
            for child in parent.get("children", []):
                if child.get("id") == sid:
                    child["status"] = "error"
                    child["errorMessage"] = data.get("error")
                    break

        elif event_type == "assistant_message":
            # 子 agent 的中间回复 → 嵌入为 assistant_reply 类型的 child step
            msg = data.get("message", "")
            if msg:
                child = {
                    "id": f"reply_{sid}", "type": "assistant_reply",
                    "name": "子Agent回复", "description": "",
                    "status": "completed", "progress": 100,
                    "thinkingContent": msg,
                }
                parent.setdefault("children", []).append(child)

        elif event_type == "completed":
            # 子 agent 的最终回复 → 嵌入为 assistant_reply 类型的 child step
            msg = data.get("message", "")
            if msg:
                child = {
                    "id": f"final_{sid}", "type": "assistant_reply",
                    "name": "填表完成" if data.get("result") else "任务完成",
                    "description": "",
                    "status": "completed", "progress": 100,
                    "thinkingContent": msg,
                }
                parent.setdefault("children", []).append(child)

    def process_event(self, event_type: str, data: dict, step_id: Optional[str] = None):
        """处理一个 SSE 事件，更新内部状态"""
        sid = step_id or f"step_{len(self._ordered_ids)}"

        # 处理委派结束
        if data.get("is_delegation_end"):
            parent = self._get_parent_step()
            if parent:
                parent["status"] = "completed"
                parent["progress"] = 100
            self._current_agent_name = None
            self._agent_parent_step_id = None
            return

        # 子 agent 事件路由到 children
        if self._is_child_agent_event(data):
            self._handle_child_event(event_type, data, step_id)
            return

        if event_type == "step_start":
            step_type = "agent_delegation" if data.get("is_delegation_start") else self._infer_type(data.get("step_name", ""))
            step = {
                "id": sid, "type": step_type, "name": data.get("step_name", ""),
                "description": data.get("description", ""), "status": "running", "progress": 0,
            }
            if data.get("is_delegation_start"):
                step["agentName"] = data.get("agent_name")
                step["children"] = []
                self._current_agent_name = data.get("agent_name")
                self._agent_parent_step_id = sid
            self._ensure_step(sid, step)

        elif event_type == "step_progress":
            s = self._steps.get(sid)
            if s:
                s["progress"] = data.get("progress", 0)

        elif event_type == "step_end":
            s = self._steps.get(sid)
            if s:
                s["status"] = "completed"
                s["progress"] = 100

        elif event_type == "tool_call":
            step = {
                "id": sid, "type": "tool_call", "name": f"调用 {data.get('tool_name', '')}",
                "description": f"执行工具: {data.get('tool_name', '')}", "status": "running", "progress": 50,
                "toolName": data.get("tool_name"), "toolParams": data.get("parameters"),
            }
            self._ensure_step(sid, step)

        elif event_type == "tool_result":
            s = self._steps.get(sid)
            if s:
                s["status"] = "completed"
                s["progress"] = 100
                s["toolResult"] = data.get("result")

        elif event_type == "tool_error":
            s = self._steps.get(sid)
            if s:
                s["status"] = "error"
                s["errorMessage"] = data.get("error")

        elif event_type == "thinking_start":
            s = self._steps.get(sid)
            if s:
                s["status"] = "running"
                s["name"] = data.get("message", s.get("name", ""))
            else:
                step = {
                    "id": sid, "type": "thinking", "name": data.get("message", "思考中"),
                    "description": "Agent正在分析任务", "status": "running", "progress": 0,
                    "thinkingContent": "",
                }
                self._ensure_step(sid, step)

        elif event_type == "thinking_chunk":
            s = self._steps.get(sid)
            if not s:
                s = {"id": sid, "type": "thinking", "name": "思考中", "description": "Agent正在分析任务",
                     "status": "running", "progress": 0, "thinkingContent": ""}
                self._ensure_step(sid, s)
            s["thinkingContent"] = s.get("thinkingContent", "") + (data.get("content", "") or "")

        elif event_type == "thinking_end":
            s = self._steps.get(sid)
            if s:
                s["status"] = "completed"
                s["progress"] = 100
                s["name"] = "思考完成"

        elif event_type == "content_chunk":
            self._pending_content += data.get("content", "") or ""

        elif event_type == "content_end":
            s = self._steps.get(sid)
            if s:
                s["status"] = "completed"
                s["progress"] = 100

        elif event_type == "assistant_message":
            # 新的一轮对话开始，标记状态（steps 由外部持久化代码获取后再 reset 清空）
            self._current_agent_name = None
            self._agent_parent_step_id = None

        elif event_type == "data_retrieval_start":
            step = {
                "id": sid, "type": "data_retrieval", "name": f"查询 {data.get('source', '')}",
                "description": f"从 {data.get('source', '')} 检索数据", "status": "running", "progress": 0,
            }
            self._ensure_step(sid, step)

        elif event_type == "data_retrieval_progress":
            s = self._steps.get(sid)
            if s:
                s["progress"] = 50 if data.get("records_found", 0) > 0 else 0

        elif event_type == "fill_table_progress":
            s = self._steps.get(sid)
            if not s:
                s = {"id": sid, "type": "fill_table", "name": "填写表格",
                     "description": "正在将数据填入模板", "status": "running", "progress": 0}
                self._ensure_step(sid, s)
            s["progress"] = data.get("progress", 0)

        elif event_type == "completed":
            # 标记所有 running 的 step 完成
            for s in self._steps.values():
                if s.get("status") == "running":
                    s["status"] = "completed"
                    s["progress"] = 100

        elif event_type in ("failed", "error"):
            error_msg = data.get("error", data.get("message", "任务失败"))
            eid = step_id or f"step_fail_{len(self._ordered_ids)}"
            existing = self._steps.get(eid)
            if existing:
                existing["status"] = "error"
                existing["errorMessage"] = error_msg
            else:
                step = {
                    "id": eid, "type": "thinking", "name": "任务失败" if event_type == "failed" else "错误",
                    "description": error_msg, "status": "error", "progress": 0,
                    "errorMessage": error_msg,
                }
                self._ensure_step(eid, step)

    def get_steps(self) -> list[dict]:
        """返回已构建的 steps 列表"""
        return [self._steps[k] for k in self._ordered_ids if k in self._steps]

    def get_pending_content(self) -> str:
        """返回尚未被 assistant_message 消费的 streaming content"""
        return self._pending_content

    def has_content(self) -> bool:
        return bool(self._pending_content) or bool(self._steps)

    def reset(self):
        """清空所有累积状态（在 assistant_message 持久化后调用）"""
        self._steps.clear()
        self._ordered_ids.clear()
        self._pending_content = ""
        self._current_agent_name = None
        self._agent_parent_step_id = None

    def _ensure_step(self, sid: str, step: dict):
        if sid not in self._steps:
            self._ordered_ids.append(sid)
        self._steps[sid] = step

    @staticmethod
    def _infer_type(step_name: str) -> str:
        if "查询" in step_name or "检索" in step_name:
            return "data_retrieval"
        if "填写" in step_name or "填表" in step_name:
            return "fill_table"
        if "调用" in step_name:
            return "tool_call"
        return "thinking"


# ============================================================
# 辅助函数
# ============================================================

def _parse_sse_event(event_str: str) -> Optional[dict]:
    """从 SSE 格式字符串中解析出 {type, data, step_id} 或 None"""
    try:
        for line in event_str.split("\n"):
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                return {
                    "type": event_data.get("event_type", ""),
                    "data": event_data,
                    "step_id": event_data.get("step_id"),
                }
    except (json.JSONDecodeError, IndexError):
        pass
    return None


def _extract_action_data(event_data: dict) -> Optional[dict]:
    """从 completed 事件数据中提取 action_data"""
    result = event_data.get("result", {})
    if result.get("download_url"):
        return {
            "action_type": "completed",
            "filled_file_url": result["download_url"],
            "filled_file_id": result.get("output_file_id"),
        }
    return None


async def _save_message(
    conversation_id: str,
    role: str,
    content: str,
    action_data: Optional[dict] = None,
    steps: Optional[list] = None,
):
    """将消息保存到数据库（后端统一持久化）

    使用 shield 保护保存操作不被 CancelledError 中断。
    """
    import asyncio as _asyncio

    async def _do_save():
        async with async_session() as db:
            msg = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                action_data=action_data,
                steps=steps,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            logger.info(f"[Persist] 消息已保存 | id={msg.id} | conv={conversation_id} | role={role} | len={len(content)} | steps={len(steps) if steps else 0}")

    try:
        task = _asyncio.ensure_future(_do_save())
        await _asyncio.shield(task)
    except _asyncio.CancelledError:
        await task
    except Exception as e:
        logger.error(f"[Persist] 保存消息失败 | conv={conversation_id} | role={role} | error={e}", exc_info=True)


# ============================================================
# API 端点
# ============================================================

class AgentStreamRequest(BaseModel):
    """流式Agent请求"""
    message: str = Field("", description="用户消息")
    file_ids: List[str] = Field(default_factory=list, description="源文档ID列表")
    template_id: Optional[str] = Field(None, description="模板文档ID")
    conversation_id: Optional[str] = Field(None, description="对话ID")
    task_type: str = Field("auto", description="任务类型: auto/fill_table/query/operation")
    task_id: Optional[str] = Field(None, description="重连时携带的任务ID")


@router.post("/stream")
async def agent_stream(request: AgentStreamRequest):
    """
    流式Agent对话接口

    使用SSE(Server-Sent Events)格式实时推送Agent执行过程。
    支持断线重连：首次请求返回 task_id，断连后携带 task_id 接入已有任务。
    """

    # === 情况1: 重连 — 接入已有任务 ===
    if request.task_id:
        logger.info(f"[API /agent/stream] 重连请求 | task_id={request.task_id}")
        task = await task_manager.get_task(request.task_id)
        if task and task.user_cancelled:
            return StreamingResponse(
                _replay_history(task),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Task-Id": task.task_id}
            )
        elif task and not task.stream.is_closed():
            return StreamingResponse(
                _replay_and_stream(task),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Task-Id": task.task_id}
            )
        elif task:
            return StreamingResponse(
                _replay_history(task),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Task-Id": task.task_id}
            )
        else:
            return StreamingResponse(
                _task_not_found_response(request.task_id),
                media_type="text/event-stream"
            )

    # === 情况2: 新任务 ===
    logger.info("=" * 70)
    logger.info("[API /agent/stream] 收到新任务请求")
    logger.info(f"[API /agent/stream] 消息: {request.message[:100]}..." if len(request.message) > 100 else f"[API /agent/stream] 消息: {request.message}")
    logger.info(f"[API /agent/stream] 文件数: {len(request.file_ids)} | 文件IDs: {request.file_ids}")
    logger.info(f"[API /agent/stream] 模板ID: {request.template_id}")
    logger.info(f"[API /agent/stream] 任务类型: {request.task_type}")
    logger.info(f"[API /agent/stream] 对话ID: {request.conversation_id}")

    # 加载对话历史
    conversation_history = []
    if request.conversation_id:
        try:
            async with async_session() as db:
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

    return StreamingResponse(
        _new_task_stream(request, conversation_history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"}
    )


# ============================================================
# 流式生成器
# ============================================================

async def _new_task_stream(request: AgentStreamRequest, conversation_history: list):
    """新任务的事件流：创建任务 → 发送 task_id → 运行 agent → 持久化 → 清理"""
    task = await task_manager.create_task(conversation_id=request.conversation_id)
    event_count = 0
    cancelled = False

    # 创建 StepAccumulator 并挂载到 task（供 cancel 端点使用）
    accumulator = StepAccumulator()
    task.step_accumulator = accumulator

    try:
        # 后端统一持久化：保存用户消息
        if request.conversation_id and request.message:
            await _save_message(request.conversation_id, "user", request.message)
            logger.info(f"[Persist] 用户消息已保存: {request.message[:80]}")

        # 首先发送 task_id 事件（前端提取后用于重连）
        task_id_event = AgentEvent(
            event_type=AgentEventType.SYSTEM_MESSAGE,
            data={"task_id": task.task_id}
        )
        yield task_id_event.to_sse_format()
        task.stream._event_history.append(task_id_event.to_sse_format())

        agent = create_general_agent(stream_manager_provider=lambda: task.stream)

        async for event in agent.run_stream(
            message=request.message,
            file_ids=request.file_ids,
            template_id=request.template_id,
            conversation_history=conversation_history,
            stream_manager=task.stream
        ):
            event_count += 1
            yield event

            # 后端统一持久化：处理每个 SSE 事件
            if request.conversation_id:
                try:
                    event_info = _parse_sse_event(event)
                    if event_info:
                        accumulator.process_event(
                            event_info["type"], event_info["data"], event_info.get("step_id")
                        )

                        # 子 agent 的 assistant_message/completed 不保存为独立消息
                        # 已通过 StepAccumulator._handle_child_event 嵌入到委派步骤的 children 中
                        is_child = bool(event_info["data"].get("agent_name"))

                        if event_info["type"] == "assistant_message" and not is_child:
                            msg = event_info["data"].get("message", "")
                            if msg:
                                steps = accumulator.get_steps()
                                await _save_message(request.conversation_id, "assistant", msg, steps=steps)
                                task.last_saved_content = msg
                                accumulator.reset()
                                logger.info(f"[Persist] assistant_message saved: {msg[:80]} | steps={len(steps)}")

                        elif event_info["type"] == "completed" and not is_child:
                            msg = event_info["data"].get("message", "")
                            if msg and msg != task.last_saved_content:
                                action_data = _extract_action_data(event_info["data"])
                                steps = accumulator.get_steps()
                                await _save_message(request.conversation_id, "assistant", msg, action_data=action_data, steps=steps)
                                logger.info(f"[Persist] completed saved: {msg[:80]} | steps={len(steps)}")
                            elif msg == task.last_saved_content:
                                logger.info(f"[Persist] completed skipped (duplicate): {msg[:80]}")
                except Exception as e:
                    logger.warning(f"[Persist] 事件处理异常: {e}", exc_info=True)

        logger.info(f"[API /agent/stream] 任务流结束 | task_id={task.task_id} | 共发送 {event_count} 个事件")

    except asyncio.CancelledError:
        if task.user_cancelled:
            logger.info(f"[API /agent/stream] 用户取消任务 | task_id={task.task_id} | 已发送 {event_count} 个事件")
        else:
            logger.info(f"[API /agent/stream] 客户端断开连接 | task_id={task.task_id} | 已发送 {event_count} 个事件 | 等待重连")
            cancelled = True
        raise

    except Exception as e:
        logger.exception(f"[API /agent/stream] 任务执行失败: {e}")
        # 异常时保存累积的 steps 和 content
        if request.conversation_id and accumulator.has_content():
            content = accumulator.get_pending_content() or f"执行出错: {str(e)}"
            steps = accumulator.get_steps()
            await _save_message(request.conversation_id, "assistant", content, steps=steps)
            logger.info(f"[Persist] 异常时保存累积内容: {content[:80]} | steps={len(steps)}")
        if not task.stream.is_closed():
            await task.stream.emit_failed(str(e))
            yield AgentEvent(
                event_type=AgentEventType.FAILED,
                data={"error": str(e)}
            ).to_sse_format()

    finally:
        if not cancelled:
            await task_manager.finish_task(task.task_id)
            asyncio.create_task(_delayed_cleanup(task.task_id, delay=600))


async def _replay_and_stream(task):
    """重连：回放历史事件（跳过已持久化消息），然后继续实时流"""
    history = task.stream.get_history()

    # 检查历史中是否已有结束事件
    already_finished = any(
        '"event_type": "completed"' in s or
        '"event_type": "failed"' in s or
        '"event_type": "cancelled"' in s
        for s in history
    )

    logger.info(f"[API /agent/stream] 重连回放 {len(history)} 个历史事件 | task_id={task.task_id} | 已完成={already_finished}")

    # 创建 accumulator 用于重建步骤状态
    accumulator = StepAccumulator()
    task.step_accumulator = accumulator

    # 1. 回放历史事件（跳过已持久化的 assistant_message，但保留 completed）
    for sse_data in history:
        if '"event_type": "assistant_message"' in sse_data:
            continue
        # 回放时也经过 accumulator，重建步骤状态
        event_info = _parse_sse_event(sse_data)
        if event_info:
            accumulator.process_event(event_info["type"], event_info["data"], event_info.get("step_id"))
        yield sse_data

    # 2. 如果任务已结束，只回放历史
    if already_finished:
        logger.info(f"[API /agent/stream] 任务已结束，仅回放历史 | task_id={task.task_id}")
        if not task.finished_at:
            await task_manager.finish_task(task.task_id)
        asyncio.create_task(_delayed_cleanup(task.task_id, delay=600))
        return

    # 3. 继续实时流（如果任务还在运行），同时持久化消息到数据库
    if not task.stream.is_closed():
        event_count = 0
        async for event in task.stream.stream():
            event_count += 1
            yield event

            # 后端统一持久化
            if task.conversation_id:
                try:
                    event_info = _parse_sse_event(event)
                    if event_info:
                        accumulator.process_event(
                            event_info["type"], event_info["data"], event_info.get("step_id")
                        )

                        # 子 agent 的 assistant_message/completed 不保存为独立消息
                        is_child = bool(event_info["data"].get("agent_name"))

                        if event_info["type"] == "assistant_message" and not is_child:
                            msg = event_info["data"].get("message", "")
                            if msg:
                                steps = accumulator.get_steps()
                                await _save_message(task.conversation_id, "assistant", msg, steps=steps)
                                task.last_saved_content = msg
                                accumulator.reset()
                                logger.info(f"[Persist/Reconnect] assistant_message saved: {msg[:80]} | steps={len(steps)}")

                        elif event_info["type"] == "completed" and not is_child:
                            msg = event_info["data"].get("message", "")
                            if msg and msg != task.last_saved_content:
                                action_data = _extract_action_data(event_info["data"])
                                steps = accumulator.get_steps()
                                await _save_message(task.conversation_id, "assistant", msg, action_data=action_data, steps=steps)
                                logger.info(f"[Persist/Reconnect] completed saved: {msg[:80]} | steps={len(steps)}")
                except Exception as e:
                    logger.warning(f"[Persist/Reconnect] 事件处理异常: {e}", exc_info=True)

        logger.info(f"[API /agent/stream] 重连实时流结束 | task_id={task.task_id} | 额外发送 {event_count} 个事件")

    # 标记任务完成
    await task_manager.finish_task(task.task_id)
    asyncio.create_task(_delayed_cleanup(task.task_id, delay=600))


async def _replay_history(task):
    """任务已完成，回放所有历史事件（跳过已持久化消息），同时持久化未保存的消息"""
    history = task.stream.get_history()
    logger.info(f"[API /agent/stream] 回放已完成任务 | task_id={task.task_id} | {len(history)} 个事件")

    # 用 accumulator 重建步骤状态，用于持久化
    accumulator = StepAccumulator()

    for sse_data in history:
        if '"event_type": "assistant_message"' in sse_data:
            continue
        yield sse_data

        # 回放时也做持久化（处理断连期间任务在后台完成的情况）
        if task.conversation_id:
            try:
                event_info = _parse_sse_event(sse_data)
                if event_info:
                    accumulator.process_event(
                        event_info["type"], event_info["data"], event_info.get("step_id")
                    )
                    is_child = bool(event_info["data"].get("agent_name"))

                    if event_info["type"] == "assistant_message" and not is_child:
                        msg = event_info["data"].get("message", "")
                        if msg:
                            steps = accumulator.get_steps()
                            await _save_message(task.conversation_id, "assistant", msg, steps=steps)
                            task.last_saved_content = msg
                            accumulator.reset()
                            logger.info(f"[Persist/Replay] assistant_message saved: {msg[:80]}")

                    elif event_info["type"] == "completed" and not is_child:
                        msg = event_info["data"].get("message", "")
                        if msg and msg != task.last_saved_content:
                            action_data = _extract_action_data(event_info["data"])
                            steps = accumulator.get_steps()
                            await _save_message(task.conversation_id, "assistant", msg, action_data=action_data, steps=steps)
                            logger.info(f"[Persist/Replay] completed saved: {msg[:80]}")
            except Exception as e:
                logger.warning(f"[Persist/Replay] 事件处理异常: {e}", exc_info=True)

    if not task.finished_at:
        await task_manager.finish_task(task.task_id)
    asyncio.create_task(_delayed_cleanup(task.task_id, delay=600))


async def _task_not_found_response(task_id: str):
    """任务不存在的响应"""
    logger.warning(f"[API /agent/stream] 任务不存在: {task_id}")
    event = AgentEvent(
        event_type=AgentEventType.FAILED,
        data={"error": "任务不存在或已过期"}
    )
    yield event.to_sse_format()


async def _delayed_cleanup(task_id: str, delay: int = 600):
    """延迟清理任务"""
    await asyncio.sleep(delay)
    await task_manager.remove_task(task_id)


@router.delete("/stream/{task_id}")
async def cancel_agent_task(task_id: str):
    """彻底取消任务（用户主动停止）"""
    task = await task_manager.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": "任务不存在或已过期"}

    # 标记用户主动取消
    task.user_cancelled = True

    # 后端统一持久化：保存累积的 steps 和 content（仅在有实际内容时保存）
    if task.conversation_id and task.step_accumulator:
        acc = task.step_accumulator
        content = acc.get_pending_content()
        steps = acc.get_steps()
        if content and content != task.last_saved_content:
            await _save_message(task.conversation_id, "assistant", content, steps=steps)
            logger.info(f"[Persist] 取消时保存累积内容: {content[:80]} | steps={len(steps)}")
        elif steps:
            # 没有 content 但有 steps，保存 steps
            await _save_message(task.conversation_id, "assistant", "", steps=steps)
            logger.info(f"[Persist] 取消时保存 steps: {len(steps)}")

    # 关闭 stream，使 runtime 中的循环收到信号
    if not task.stream.is_closed():
        await task.stream.emit_cancelled("任务已取消")
        await task.stream.close()

    # 标记任务完成
    await task_manager.finish_task(task_id)
    asyncio.create_task(_delayed_cleanup(task_id, delay=600))

    logger.info(f"[API /agent/stream] 任务已取消 | task_id={task_id}")
    return {"status": "ok"}
