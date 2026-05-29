"""
任务管理器 - 管理运行中的Agent任务

每个任务有唯一 task_id，前端首次请求时获得。
断线重连时携带 task_id 接入已有任务，不重启。
"""

import asyncio
import uuid
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.agent.core.stream import StreamManager


logger = logging.getLogger(__name__)

# 任务最大保留时间（完成/失败后保留，供重连回放）
TASK_TTL = timedelta(minutes=10)


@dataclass
class Task:
    task_id: str
    stream: StreamManager
    conversation_id: Optional[str] = None  # 对话ID，用于持久化消息
    created_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None  # 完成/失败的时间
    result: Optional[dict] = None  # 完成/失败的结果数据
    user_cancelled: bool = False  # 用户主动取消标记
    step_accumulator: Optional[object] = None  # StepAccumulator 实例（由 agent_stream 模块设置）
    last_saved_content: str = ""  # 最后保存的消息内容，用于去重
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)  # 用户取消信号
    reconnect_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # 重连锁，防止同一任务被多个连接同时接入
    active_reconnections: int = 0  # 当前活跃的重连数


class TaskManager:
    """全局任务注册表"""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()

    async def create_task(self, conversation_id: Optional[str] = None) -> Task:
        """创建新任务"""
        task_id = uuid.uuid4().hex[:8]
        stream = StreamManager()
        task = Task(task_id=task_id, stream=stream, conversation_id=conversation_id)
        async with self._lock:
            self._tasks[task_id] = task
        logger.info(f"[TaskManager] 创建任务: {task_id}")
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """查询任务"""
        async with self._lock:
            return self._tasks.get(task_id)

    async def get_running_task_by_conversation(self, conversation_id: str) -> Optional[Task]:
        """查找指定对话中正在运行的任务"""
        if not conversation_id:
            return None
        async with self._lock:
            for task in self._tasks.values():
                if (task.conversation_id == conversation_id
                        and not task.finished_at
                        and not task.user_cancelled):
                    return task
            return None

    async def finish_task(self, task_id: str, result: Optional[dict] = None):
        """标记任务完成"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.finished_at = datetime.utcnow()
                task.result = result
                logger.info(f"[TaskManager] 任务完成: {task_id}")

    async def remove_task(self, task_id: str):
        """移除任务"""
        async with self._lock:
            self._tasks.pop(task_id, None)
            logger.info(f"[TaskManager] 移除任务: {task_id}")

    async def cleanup_expired(self):
        """清理过期任务"""
        now = datetime.utcnow()
        expired = []
        async with self._lock:
            for task_id, task in self._tasks.items():
                if task.finished_at and now - task.finished_at > TASK_TTL:
                    expired.append(task_id)
        for task_id in expired:
            await self.remove_task(task_id)
        if expired:
            logger.info(f"[TaskManager] 清理过期任务: {expired}")


# 全局实例
task_manager = TaskManager()
