"""
Agent编排器 - 核心入口

负责：
- 请求分发（dispatch）
- 任务委派（delegate）
- 并行执行（parallel_execute）
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import asyncio
import logging

from app.agent.core.registry import ToolRegistry
from app.agent.core.runtime import AgentRuntime
from app.agent.core.stream import StreamManager
from app.agent.base.tool import ToolContext

logger = logging.getLogger(__name__)


@dataclass
class DelegationTask:
    """委派任务"""
    task_id: str
    target_agent: str
    description: str
    context: Dict[str, Any]
    priority: int = 0
    timeout_ms: int = 120000


@dataclass
class DelegationResult:
    """委派结果"""
    task_id: str
    success: bool
    result: Dict[str, Any]
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    duration_ms: int = 0


class AgentOrchestrator:
    """Agent编排器

    核心入口，负责请求分发、任务委派、并行执行。
    """

    def __init__(
        self,
        agent_factory: 'AgentFactory',
        delegation_manager: 'DelegationManager'
    ):
        """初始化Agent编排器

        Args:
            agent_factory: Agent工厂
            delegation_manager: 委派管理器
        """
        self.agent_factory = agent_factory
        self.delegation_manager = delegation_manager

    async def dispatch(
        self,
        user_message: str,
        context: ToolContext,
        preferred_agent: Optional[str] = None,
        stream_manager: Optional[StreamManager] = None
    ) -> Dict[str, Any]:
        """请求分发

        Args:
            user_message: 用户消息
            context: 工具上下文
            preferred_agent: 首选Agent类型（可选）
            stream_manager: 流管理器（可选）

        Returns:
            执行结果
        """
        logger.info(f"[AgentOrchestrator] 分发请求 | preferred_agent={preferred_agent}")

        # 如果指定了首选Agent，直接路由
        if preferred_agent:
            agent_type = preferred_agent
        else:
            # 使用PlannerAgent分析意图
            agent_type = await self._analyze_intent(user_message, context)

        # 创建Agent实例
        agent = self.agent_factory.create(agent_type)

        # 执行Agent
        result = await agent.run(
            message=user_message,
            file_ids=context.file_ids,
            template_id=context.template_id,
            user_id=context.user_id
        )

        return result

    async def delegate(
        self,
        parent_agent: str,
        task: DelegationTask,
        stream_manager: Optional[StreamManager] = None
    ) -> DelegationResult:
        """任务委派

        Args:
            parent_agent: 父Agent名称
            task: 委派任务
            stream_manager: 流管理器（可选）

        Returns:
            委派结果
        """
        logger.info(f"[AgentOrchestrator] 委派任务 | {parent_agent} -> {task.target_agent}")

        return await self.delegation_manager.delegate(task, stream_manager)

    async def parallel_execute(
        self,
        tasks: List[DelegationTask],
        stream_manager: Optional[StreamManager] = None
    ) -> List[DelegationResult]:
        """并行执行多个任务

        Args:
            tasks: 任务列表
            stream_manager: 流管理器（可选）

        Returns:
            结果列表
        """
        logger.info(f"[AgentOrchestrator] 并行执行 {len(tasks)} 个任务")

        return await self.delegation_manager.delegate_parallel(tasks, stream_manager)

    async def _analyze_intent(
        self,
        user_message: str,
        context: ToolContext
    ) -> str:
        """分析用户意图，选择Agent类型

        Args:
            user_message: 用户消息
            context: 工具上下文

        Returns:
            Agent类型名称
        """
        # 使用LLM分析意图
        from app.services.llm_service import llm_service

        prompt = f"""分析用户意图，选择最合适的Agent类型。

可用的Agent类型：
- editor: 文档内容读取、编辑、格式调整、转换
- data: 数据查询、提取、统计分析
- knowledge: 知识图谱查询、构建、实体关系分析
- table: 模板表格结构分析、数据填写
- search: 跨文档搜索、RAG检索、信息定位

用户消息：{user_message}

请只返回Agent类型名称（editor/data/knowledge/table/search），不要其他内容。"""

        try:
            response = await llm_service.generate(
                prompt=prompt,
                max_tokens=20,
                temperature=0
            )

            agent_type = response.strip().lower()

            # 验证Agent类型
            valid_types = ["editor", "data", "knowledge", "table", "search"]
            if agent_type in valid_types:
                return agent_type
            else:
                # 默认使用editor
                return "editor"

        except Exception as e:
            logger.error(f"意图分析失败: {e}")
            return "editor"
