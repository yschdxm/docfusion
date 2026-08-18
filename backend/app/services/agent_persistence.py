"""
Agent 消息持久化订阅者

后端是消息持久化的唯一权威。AgentPersistence 作为 TaskEventLog 的一个订阅者，
在任务创建时以 after_seq=0 挂载，直接消费 AgentEvent 对象（不再解析 SSE 字符串），
生命周期绑定任务而非 HTTP 连接 —— 客户端断开、重连、多设备查看都不影响持久化。

职责：
- 用 StepAccumulator 累积事件，构建 steps 数据
- assistant_message / completed 事件时保存 assistant 消息
- 终态（failed/cancelled）时保存累积的部分内容与 steps
"""

import asyncio
import logging
import re
from typing import Optional


from app.agent.core.event_log import TaskEventLog
from app.agent.core.stream import AgentEvent, AgentEventType
from app.db.postgres import async_session
from app.models.document import Message


logger = logging.getLogger(__name__)


# ============================================================
# StepAccumulator — 累积事件，构建 steps 数据
# ============================================================

class StepAccumulator:
    """累积 AgentEvent 流，构建 steps 数据和 streaming content。

    用于后端持久化时将完整的 steps 信息写入 Message.steps 字段。
    与前端 agentStreamService._processEvent 逻辑同构（修改时需同步）。
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
        """处理一个事件，更新内部状态"""
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
# 消息保存辅助函数
# ============================================================

def _normalize_download_urls(content: str) -> str:
    """规范化消息中的下载链接，修复LLM生成的错误URL

    处理以下错误格式：
    1. https://www1.fylm.xyz:9200/api/v1/documents/... → /api/v1/documents/...
    2. http://api/v1/documents/... → /api/v1/documents/...
    3. 任何包含 /documents/{uuid}/download 的完整URL → 相对路径
    """
    if not content:
        return content

    # 匹配 Markdown 链接中的下载URL: [text](url)
    # 也匹配纯文本URL
    def fix_url(match):
        prefix = match.group(1)  # 可能的 [text]( 前缀
        url = match.group(2)
        suffix = match.group(3)  # 可能的 ) 后缀

        # 检查是否是下载链接
        if '/documents/' in url and '/download' in url:
            # 提取路径部分
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                return f"{prefix}{parsed.path}{suffix}"
            except Exception:
                # 如果解析失败，尝试正则提取
                path_match = re.search(r'(/api/v1/documents/[\w-]+/download)', url)
                if path_match:
                    return f"{prefix}{path_match.group(1)}{suffix}"

        return match.group(0)  # 不是下载链接，返回原值

    # 匹配 Markdown 链接格式: [text](url)
    content = re.sub(r'(\[[^\]]*\]\()([^)]+)(\))', fix_url, content)

    # 匹配纯文本URL（不在Markdown链接中的）
    def fix_plain_url(match):
        url = match.group(0)
        if '/documents/' in url and '/download' in url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                return parsed.path
            except Exception:
                path_match = re.search(r'(/api/v1/documents/[\w-]+/download)', url)
                if path_match:
                    return path_match.group(1)
        return url

    # 匹配 http:// 或 https:// 开头的URL
    content = re.sub(r'https?://[^\s\)]+', fix_plain_url, content)

    return content


def _extract_action_data(event_data: dict) -> Optional[dict]:
    """从 completed 事件数据中提取 action_data"""
    result = event_data.get("result", {})
    if result.get("download_url"):
        return {
            "action_type": "completed",
            "filled_file_url": result["download_url"],
            "filled_file_id": result.get("output_file_id"),
            "filled_filename": result.get("output_filename"),
        }
    return None


async def save_message(
    conversation_id: str,
    role: str,
    content: str,
    action_data: Optional[dict] = None,
    steps: Optional[list] = None,
    task_stats: Optional[dict] = None,
):
    """将消息保存到数据库（后端统一持久化）

    使用 shield 保护保存操作不被 CancelledError 中断。
    """
    # 规范化消息中的下载链接（只处理assistant消息）
    if role == "assistant" and content:
        content = _normalize_download_urls(content)

    # JSON 安全化：PG numeric 列的 Decimal 等类型会导致 JSON 列插入 TypeError，
    # 不拦截会让整条消息从对话历史中丢失（曾发生：含查询结果的 steps 落库失败）
    from app.core.json_utils import jsonable
    action_data = jsonable(action_data)
    steps = jsonable(steps)
    task_stats = jsonable(task_stats)

    async def _do_save():
        async with async_session() as db:
            msg = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                action_data=action_data,
                steps=steps,
                task_stats=task_stats,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            logger.info(f"[Persist] 消息已保存 | id={msg.id} | conv={conversation_id} | role={role} | len={len(content)} | steps={len(steps) if steps else 0} | stats={'yes' if task_stats else 'no'}")

    try:
        task = asyncio.ensure_future(_do_save())
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
    except Exception as e:
        logger.error(f"[Persist] 保存消息失败 | conv={conversation_id} | role={role} | error={e}", exc_info=True)


# ============================================================
# AgentPersistence — 事件持久化订阅者
# ============================================================

class AgentPersistence:
    """任务事件持久化订阅者

    在任务创建时挂载到 TaskEventLog（after_seq=0），消费全部事件对象并落库。
    生命周期绑定任务：HTTP 连接断开/重连不影响持久化，任务结束时由
    TaskSupervisor 等待其处理完终态事件。
    """

    def __init__(self, conversation_id: Optional[str]):
        self.conversation_id = conversation_id
        self.accumulator = StepAccumulator()
        self.last_saved_content = ""  # 最后保存的消息内容，用于去重

    async def run(self, event_log: TaskEventLog) -> None:
        """订阅事件日志直到任务结束（无对话ID时不落库，仅排空订阅）"""
        async for item in event_log.subscribe(after_seq=0, heartbeat=60.0):
            if item is None:  # 心跳
                continue
            if not self.conversation_id:
                continue
            try:
                await self._on_event(item)
            except Exception as e:
                logger.warning(f"[Persist] 事件处理异常: {e}", exc_info=True)

    async def _on_event(self, event: AgentEvent) -> None:
        event_type = event.event_type.value if isinstance(event.event_type, AgentEventType) else event.event_type
        data = event.data or {}
        self.accumulator.process_event(event_type, data, event.step_id)

        # 子 agent 的 assistant_message/completed 不保存为独立消息
        # 已通过 StepAccumulator._handle_child_event 嵌入到委派步骤的 children 中
        is_child = bool(data.get("agent_name"))
        if is_child:
            return

        if event_type == "assistant_message":
            msg = data.get("message", "")
            if msg:
                steps = self.accumulator.get_steps()
                await save_message(self.conversation_id, "assistant", msg, steps=steps)
                self.last_saved_content = msg
                self.accumulator.reset()
                logger.info(f"[Persist] assistant_message saved: {msg[:80]} | steps={len(steps)}")

        elif event_type == "action_required":
            # 确认卡片落库：刷新/重进会话后可恢复卡片及其状态。
            # 不携带 steps：随后的 assistant_message（校验总结）会携带同一批 steps，
            # 两处都带会在前端重复渲染
            action_data = data.get("action_data") or {}
            await save_message(
                self.conversation_id, "assistant", "",
                action_data={
                    "action_type": "confirm_fill",
                    "action_id": action_data.get("action_id"),
                    "status": "pending",
                    "summary": data.get("message", ""),
                    "dry_run_report": action_data.get("dry_run_report"),
                    "preview": action_data.get("preview"),
                },
            )
            logger.info(f"[Persist] action_required 卡片已保存 | action_id={action_data.get('action_id')}")

        elif event_type == "completed":
            msg = data.get("message", "")
            if msg and msg != self.last_saved_content:
                action_data = _extract_action_data(data)
                steps = self.accumulator.get_steps()
                task_stats = data.get("result", {}).get("task_stats")
                await save_message(self.conversation_id, "assistant", msg, action_data=action_data, steps=steps, task_stats=task_stats)
                self.last_saved_content = msg
                logger.info(f"[Persist] completed saved: {msg[:80]} | steps={len(steps)} | stats={'yes' if task_stats else 'no'}")
            elif msg and msg == self.last_saved_content:
                logger.info(f"[Persist] completed skipped (duplicate): {msg[:80]}")

        elif event_type in ("failed", "cancelled"):
            # 任务异常结束/被取消：保存累积的部分内容与 steps
            content = self.accumulator.get_pending_content()
            steps = self.accumulator.get_steps()
            if content and content != self.last_saved_content:
                await save_message(self.conversation_id, "assistant", content, steps=steps)
                logger.info(f"[Persist] {event_type} 时保存累积内容: {content[:80]} | steps={len(steps)}")
            elif steps and not content:
                # 没有 content 但有 steps，保存 steps（仅限取消场景，失败场景由 failed 消息承担）
                if event_type == "cancelled":
                    await save_message(self.conversation_id, "assistant", "", steps=steps)
                    logger.info(f"[Persist] cancelled 时保存 steps: {len(steps)}")
