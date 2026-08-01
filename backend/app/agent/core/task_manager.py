"""
任务管理器 - 管理运行中的Agent任务

核心设计：
- 显式状态机：RUNNING → COMPLETED | FAILED | CANCELLED
- 取消单一化：cancel() 设置 cancel_event + 发布 cancelled 终态事件，runtime 只检查 cancel_event
- TaskSupervisor：持有执行协程，保证终态事件恰好发布一次 + event_log.finish()
- task_id 使用完整 uuid4，避免碰撞
- get_running_or_create 原子操作，防止双击/并发创建重复任务
"""

import asyncio
import uuid
import logging
from typing import Dict, Optional, Tuple, Coroutine, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from app.agent.core.event_log import TaskEventLog
from app.agent.core.stream import AgentEventType


logger = logging.getLogger(__name__)

# 任务最大保留时间（完成/失败后保留，供重连回放）
TASK_TTL = timedelta(minutes=10)


class TaskStatus(str, Enum):
    """任务状态"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_TO_STATUS = {
    AgentEventType.COMPLETED: TaskStatus.COMPLETED,
    AgentEventType.FAILED: TaskStatus.FAILED,
    AgentEventType.CANCELLED: TaskStatus.CANCELLED,
}


@dataclass
class Task:
    task_id: str
    event_log: TaskEventLog
    conversation_id: Optional[str] = None  # 对话ID，用于持久化消息
    status: TaskStatus = TaskStatus.RUNNING
    created_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None  # 完成/失败的时间
    result: Optional[dict] = None  # 终态事件的 data
    user_cancelled: bool = False  # 用户主动取消标记
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)  # 取消信号（runtime 唯一取消来源）
    supervisor: Optional[asyncio.Task] = None  # 执行协程（由 TaskManager.start 设置）


class TaskManager:
    """全局任务注册表"""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()

    # ---------- 任务生命周期 ----------

    async def get_running_or_create(self, conversation_id: Optional[str]) -> Tuple[Task, bool]:
        """查找对话的运行中任务，没有则原子创建。返回 (task, created)。

        conversation_id 为 None 时总是创建新任务。
        在同一把锁内完成 check-then-act，杜绝并发双击创建两个任务。
        """
        async with self._lock:
            if conversation_id:
                for task in self._tasks.values():
                    if (task.conversation_id == conversation_id
                            and task.status == TaskStatus.RUNNING):
                        return task, False
            task = Task(task_id=uuid.uuid4().hex, event_log=TaskEventLog(), conversation_id=conversation_id)
            self._tasks[task.task_id] = task
            logger.info(f"[TaskManager] 创建任务: {task.task_id} | conv={conversation_id}")
            return task, True

    async def get_task(self, task_id: str) -> Optional[Task]:
        """查询任务"""
        async with self._lock:
            return self._tasks.get(task_id)

    # ---------- 执行监督 ----------

    def start(self, task: Task, agent_coro: Coroutine[Any, Any, dict], persistence=None) -> None:
        """启动任务：运行 agent 协程 + 持久化订阅者，由 supervisor 统一收尾

        supervisor 保证：
        - 终态事件恰好发布一次（runtime 已发布则不重复）
        - event_log.finish() 一定被调用
        - 任务状态与终态事件一致
        """
        task.supervisor = asyncio.create_task(
            self._supervise(task, agent_coro, persistence),
            name=f"task-supervisor-{task.task_id[:8]}",
        )

    async def _supervise(self, task: Task, agent_coro: Coroutine[Any, Any, dict], persistence) -> None:
        log = task.event_log
        persist_task: Optional[asyncio.Task] = None
        if persistence is not None:
            persist_task = asyncio.create_task(
                persistence.run(log),
                name=f"task-persist-{task.task_id[:8]}",
            )

        try:
            result = await agent_coro
            if log.terminal_event is None:
                # runtime 未发布终态事件的兜底（正常路径 runtime 会自己发布）
                if result and result.get("success"):
                    await log.emit_completed(result.get("message") or "", result.get("result_data") or {})
                else:
                    await log.emit_failed((result or {}).get("error") or "任务失败")
        except asyncio.CancelledError:
            logger.info(f"[TaskManager] 执行协程被取消 | task_id={task.task_id[:8]}")
            if log.terminal_event is None:
                await log.emit_cancelled("任务已取消")
        except Exception as e:
            logger.exception(f"[TaskManager] 执行协程异常 | task_id={task.task_id[:8]} | error={e}")
            if log.terminal_event is None:
                await log.emit_failed(str(e))
        finally:
            # 状态与终态事件对齐
            terminal = log.terminal_event
            if terminal is not None:
                task.status = _TERMINAL_TO_STATUS.get(terminal.event_type, TaskStatus.FAILED)
                task.result = terminal.data
            else:
                task.status = TaskStatus.FAILED
            task.finished_at = datetime.utcnow()
            await log.finish()

            # 等待持久化订阅者处理完终态事件（有界等待，防止悬挂）
            if persist_task is not None:
                try:
                    await asyncio.wait_for(persist_task, timeout=30.0)
                except Exception as e:
                    logger.warning(f"[TaskManager] 持久化订阅者收尾异常: {e}")

            logger.info(
                f"[TaskManager] 任务结束 | task_id={task.task_id[:8]} | status={task.status.value} | "
                f"events={log.last_seq}"
            )
            # 延迟清理，保留缓冲供重连回放
            try:
                asyncio.create_task(self._delayed_remove(task.task_id))
            except RuntimeError:
                # 事件循环已关闭（测试环境），由 cleanup_expired 兜底
                pass

    async def cancel(self, task_id: str) -> bool:
        """彻底取消任务（用户主动停止）。幂等。

        单一取消路径：标记 + 置 cancel_event + 发布 cancelled 终态事件 + 取消执行协程。
        runtime 只检查 cancel_event；supervisor 负责 finish。
        """
        task = await self.get_task(task_id)
        if not task or task.status != TaskStatus.RUNNING:
            return False

        task.user_cancelled = True
        task.cancel_event.set()
        # 发布终态事件（若 runtime 已发布终态则会被 event_log 拒绝，保证恰好一次）
        await task.event_log.emit_cancelled("任务已取消")
        # 取消执行协程，使其尽快退出（supervisor 捕获后统一 finish）
        if task.supervisor and not task.supervisor.done():
            task.supervisor.cancel()
        logger.info(f"[TaskManager] 任务已取消 | task_id={task_id[:8]}")
        return True

    # ---------- 清理 ----------

    async def remove_task(self, task_id: str):
        """移除任务"""
        async with self._lock:
            self._tasks.pop(task_id, None)
            logger.info(f"[TaskManager] 移除任务: {task_id[:8]}")

    async def _delayed_remove(self, task_id: str):
        """延迟清理任务（保留缓冲供重连回放）"""
        await asyncio.sleep(TASK_TTL.total_seconds())
        await self.remove_task(task_id)

    async def cleanup_expired(self):
        """清理过期任务（兜底，正常由 _delayed_remove 处理）"""
        now = datetime.utcnow()
        expired = []
        async with self._lock:
            for task_id, task in self._tasks.items():
                if task.finished_at and now - task.finished_at > TASK_TTL:
                    expired.append(task_id)
        for task_id in expired:
            await self.remove_task(task_id)
        if expired:
            logger.info(f"[TaskManager] 清理过期任务: {[t[:8] for t in expired]}")


# 全局实例
task_manager = TaskManager()
