"""
任务事件日志 - SSE 架构核心

事件溯源 + 发布/订阅模型，取代旧的单消费者队列 StreamManager：

- 每个任务一份有序事件日志（有界环形缓冲，事件带单调递增 seq）
- 多个订阅者各自独立消费，互不影响（HTTP 连接、持久化订阅者等）
- 断线重连通过 after_seq 断点续传（SSE 标准 id: 字段 / Last-Event-ID）
- 终态事件（completed/failed/cancelled）恰好发布一次，由 TaskSupervisor 保证
- finish() 幂等；publish 在 finish 后被拒绝

订阅者语义：
- subscribe(after_seq) 先回放缓冲中 seq > after_seq 的事件，再接实时流
- yield None 表示心跳（无新事件），由调用方决定如何渲染（如 SSE keepalive 注释行）
- 订阅者消费过慢（队列满）会被终止订阅，客户端可用 Last-Event-ID 重连续传
"""

import asyncio
import logging
from collections import deque
from typing import AsyncGenerator, Optional

from app.agent.core.stream import AgentEvent, AgentEventType


logger = logging.getLogger(__name__)


class TaskEventLog:
    """任务事件日志（有界缓冲 + 多订阅者广播）"""

    TERMINAL_TYPES = {
        AgentEventType.COMPLETED,
        AgentEventType.FAILED,
        AgentEventType.CANCELLED,
    }

    def __init__(self, max_size: int = 5000, subscriber_queue_size: int = 1000):
        self._events: deque[AgentEvent] = deque(maxlen=max_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._subscriber_queue_size = subscriber_queue_size
        self._seq = 0
        self._finished = False
        self._terminal_event: Optional[AgentEvent] = None
        self._current_step_id: Optional[str] = None  # 便捷 emit_* 方法使用的当前步骤ID

    # ---------- 状态查询 ----------

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def terminal_event(self) -> Optional[AgentEvent]:
        """已发布的终态事件（未完成时为 None）"""
        return self._terminal_event

    # ---------- 发布 ----------

    async def publish(self, event: AgentEvent) -> int:
        """发布事件，返回分配的 seq。finish 后调用会被拒绝并返回 -1。"""
        if self._finished:
            logger.warning(f"[TaskEventLog] 向已结束的日志发布事件被拒绝: {event.event_type}")
            return -1

        # 委派子Agent转发来的事件带 agent_name 标记，其终态事件不算本任务的终态
        is_terminal = event.event_type in self.TERMINAL_TYPES and not event.data.get("agent_name")

        # 终态事件恰好一次：重复的直接拒绝，不分配 seq、不入缓冲、不广播
        if is_terminal and self._terminal_event is not None:
            logger.warning(
                f"[TaskEventLog] 重复终态事件被忽略: {event.event_type} "
                f"(已有 {self._terminal_event.event_type})"
            )
            return -1

        self._seq += 1
        event.seq = self._seq
        self._events.append(event)

        if is_terminal:
            self._terminal_event = event

        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 订阅者消费过慢：终止其订阅（客户端可用 Last-Event-ID 重连续传）
                self._subscribers.discard(q)
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(None)
                logger.warning("[TaskEventLog] 订阅者消费过慢，已终止其订阅")

        if is_terminal:
            logger.info(f"[TaskEventLog] 终态事件: {event.event_type} | seq={event.seq}")

        return event.seq

    async def finish(self) -> None:
        """关闭日志（幂等）。之后 publish 被拒绝，所有订阅者收到结束标记。"""
        if self._finished:
            return
        self._finished = True
        for q in list(self._subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    # ---------- 订阅 ----------

    async def subscribe(
        self,
        after_seq: int = 0,
        heartbeat: float = 25.0,
    ) -> AsyncGenerator[Optional[AgentEvent], None]:
        """订阅事件流

        先回放缓冲中 seq > after_seq 的事件，再接实时流（按 seq 去重，无竞态）。

        Yields:
            AgentEvent: 事件对象
            None: 心跳（heartbeat 秒内无新事件）
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._subscriber_queue_size)
        self._subscribers.add(queue)
        try:
            cursor = after_seq
            # 回放缓冲（注册订阅后再回放，live 事件按 seq 去重，无遗漏无重复）
            for ev in list(self._events):
                if ev.seq is not None and ev.seq > cursor:
                    cursor = ev.seq
                    yield ev

            if self._finished:
                return

            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield None  # 心跳
                    continue

                if item is None:  # 结束标记
                    return
                if item.seq is not None and item.seq <= cursor:
                    continue  # 与回放重叠，去重
                if item.seq is not None:
                    cursor = item.seq
                yield item
        finally:
            self._subscribers.discard(queue)

    # ---------- 便捷发布方法（供 runtime 使用，保持事件构造一致） ----------

    async def emit(self, event: AgentEvent) -> int:
        """发布事件（带日志）"""
        seq = await self.publish(event)
        if seq > 0:
            logger.debug(f"[TaskEventLog] 事件: {event.event_type} | seq={seq} | step_id={event.step_id}")
        return seq

    async def emit_thinking_start(self, step_id: str, message: str = "") -> None:
        self._current_step_id = step_id
        await self.emit(AgentEvent(event_type=AgentEventType.THINKING_START, step_id=step_id, data={"message": message}))

    async def emit_thinking_chunk(self, content: str, is_complete: bool = False) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.THINKING_CHUNK, step_id=self._current_step_id, data={"content": content, "is_complete": is_complete}))

    async def emit_thinking_end(self, summary: str = "") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.THINKING_END, step_id=self._current_step_id, data={"summary": summary}))

    async def emit_tool_call(self, tool_name: str, parameters: dict) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.TOOL_CALL, step_id=self._current_step_id, data={"tool_name": tool_name, "parameters": parameters}))

    async def emit_tool_result(self, tool_name: str, result: dict, execution_time_ms: int = 0) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.TOOL_RESULT, step_id=self._current_step_id, data={"tool_name": tool_name, "result": result, "execution_time_ms": execution_time_ms}))

    async def emit_tool_error(self, tool_name: str, error: str) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.TOOL_ERROR, step_id=self._current_step_id, data={"tool_name": tool_name, "error": error}))

    async def emit_step_start(self, step_id: str, step_name: str, description: str = "") -> None:
        self._current_step_id = step_id
        await self.emit(AgentEvent(event_type=AgentEventType.STEP_START, step_id=step_id, data={"step_name": step_name, "description": description}))

    async def emit_step_progress(self, progress: float, message: str = "") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.STEP_PROGRESS, step_id=self._current_step_id, data={"progress": progress, "message": message}))

    async def emit_step_end(self, step_id: str, result_summary: str = "") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.STEP_END, step_id=step_id, data={"result_summary": result_summary}))

    async def emit_data_retrieval_start(self, source: str, query: str) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.DATA_RETRIEVAL_START, step_id=self._current_step_id, data={"source": source, "query": query}))

    async def emit_data_retrieval_progress(self, source: str, records_found: int, message: str = "") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.DATA_RETRIEVAL_PROGRESS, step_id=self._current_step_id, data={"source": source, "records_found": records_found, "message": message}))

    async def emit_data_retrieval_end(self, source: str, total_records: int, success: bool = True) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.DATA_RETRIEVAL_END, step_id=self._current_step_id, data={"source": source, "total_records": total_records, "success": success}))

    async def emit_fill_table_start(self, template_id: str, row_count: int = 0) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.FILL_TABLE_START, step_id=self._current_step_id, data={"template_id": template_id, "row_count": row_count}))

    async def emit_fill_table_progress(self, filled_rows: int, total_rows: int, message: str = "") -> None:
        progress = (filled_rows / total_rows * 100) if total_rows > 0 else 0
        await self.emit(AgentEvent(event_type=AgentEventType.FILL_TABLE_PROGRESS, step_id=self._current_step_id, data={"filled_rows": filled_rows, "total_rows": total_rows, "progress": round(progress, 1), "message": message}))

    async def emit_fill_table_end(self, filled_file_id: str, download_url: str = "") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.FILL_TABLE_END, step_id=self._current_step_id, data={"filled_file_id": filled_file_id, "download_url": download_url}))

    async def emit_content_chunk(self, content: str) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.CONTENT_CHUNK, step_id=self._current_step_id, data={"content": content}))

    async def emit_content_end(self) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.CONTENT_END, step_id=self._current_step_id, data={}))

    async def emit_assistant_message(self, message: str) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.ASSISTANT_MESSAGE, step_id=None, data={"message": message}))

    async def emit_action_required(self, action_type: str, action_data: dict, message: str = "") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.ACTION_REQUIRED, step_id=self._current_step_id, data={"action_type": action_type, "action_data": action_data, "message": message}))

    async def emit_system_message(self, message: str, level: str = "info") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.SYSTEM_MESSAGE, step_id=self._current_step_id, data={"message": message, "level": level}))

    async def emit_stats_update(self, stats: dict) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.STATS_UPDATE, step_id=self._current_step_id, data={"stats": stats}))

    async def emit_warning(self, message: str) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.WARNING, step_id=self._current_step_id, data={"message": message}))

    async def emit_error(self, error: str, details: dict = None) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.ERROR, step_id=self._current_step_id, data={"error": error, "details": details or {}}))

    # 终态事件：只负责发布，不负责 finish（由 TaskSupervisor 统一收尾，保证恰好一次）
    async def emit_completed(self, message: str, result_data: dict = None) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.COMPLETED, step_id=self._current_step_id, data={"message": message, "result": result_data or {}}))

    async def emit_failed(self, error: str, details: dict = None) -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.FAILED, step_id=self._current_step_id, data={"error": error, "details": details or {}}))

    async def emit_cancelled(self, message: str = "任务已取消") -> None:
        await self.emit(AgentEvent(event_type=AgentEventType.CANCELLED, step_id=self._current_step_id, data={"message": message}))
