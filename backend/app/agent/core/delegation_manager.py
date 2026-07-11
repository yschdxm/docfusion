"""
委派管理器 - 管理Agent间的任务委派

负责：
- 单个任务委派
- 并行任务委派
- 结果聚合
"""

from typing import Dict, Any, List, Optional
import asyncio
import logging
import uuid

from app.agent.core.orchestrator import DelegationTask, DelegationResult
from app.agent.core.factory import AgentFactory
from app.agent.core.stream import StreamManager
from app.agent.base.tool import ToolContext

logger = logging.getLogger(__name__)


class DelegationManager:
    """委派管理器

    管理Agent间的任务委派，支持单个和并行委派。
    """

    def __init__(self, agent_factory: AgentFactory):
        """初始化委派管理器

        Args:
            agent_factory: Agent工厂
        """
        self.agent_factory = agent_factory

    async def delegate(
        self,
        task: DelegationTask,
        stream_manager: Optional[StreamManager] = None
    ) -> DelegationResult:
        """委派单个任务

        Args:
            task: 委派任务
            stream_manager: 流管理器（可选）

        Returns:
            委派结果
        """
        logger.info(f"[DelegationManager] 委派任务 | {task.target_agent} | {task.description[:50]}...")

        start_time = asyncio.get_event_loop().time()

        try:
            # 创建子Agent
            child_agent = self.agent_factory.create(task.target_agent)

            # 创建子上下文
            child_context = ToolContext(
                session_id=f"delegation_{uuid.uuid4().hex[:8]}",
                user_id=task.context.get("user_id"),
                file_ids=task.context.get("file_ids", []),
                template_id=task.context.get("template_id"),
                conversation_history=task.context.get("conversation_history", [])
            )

            # 执行子Agent
            result = await child_agent.run(
                message=task.description,
                file_ids=child_context.file_ids,
                template_id=child_context.template_id,
                user_id=child_context.user_id
            )

            # 计算耗时
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

            return DelegationResult(
                task_id=task.task_id,
                success=result.get("success", False),
                result=result,
                tokens_used=result.get("tokens_used", 0),
                duration_ms=duration_ms
            )

        except Exception as e:
            logger.exception(f"[DelegationManager] 委派失败: {e}")
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

            return DelegationResult(
                task_id=task.task_id,
                success=False,
                result={"error": str(e)},
                duration_ms=duration_ms
            )

    async def delegate_parallel(
        self,
        tasks: List[DelegationTask],
        stream_manager: Optional[StreamManager] = None
    ) -> List[DelegationResult]:
        """并行委派多个任务

        Args:
            tasks: 任务列表
            stream_manager: 流管理器（可选）

        Returns:
            结果列表
        """
        logger.info(f"[DelegationManager] 并行委派 {len(tasks)} 个任务")

        # 创建协程列表
        coroutines = [self.delegate(task, stream_manager) for task in tasks]

        # 并行执行
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # 处理异常
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[DelegationManager] 任务 {tasks[i].task_id} 异常: {result}")
                final_results.append(DelegationResult(
                    task_id=tasks[i].task_id,
                    success=False,
                    result={"error": str(result)}
                ))
            else:
                final_results.append(result)

        return final_results
