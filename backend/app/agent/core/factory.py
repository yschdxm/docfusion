"""
Agent工厂 - 动态创建Agent实例

负责：
- 注册Agent类型定义
- 根据类型创建Agent实例
- 解析工具子集
- 构建系统提示词
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import logging

from app.agent.core.registry import ToolRegistry
from app.agent.core.runtime import AgentRuntime
from app.agent.core.context_manager import ContextManager, TokenBudget
from app.agent.core.hook_system import HookSystem
from app.agent.core.cache import ToolResultCache

logger = logging.getLogger(__name__)


@dataclass
class AgentTypeDefinition:
    """Agent类型定义"""
    name: str                          # 类型名，如 "planner", "editor"
    display_name: str                  # 显示名称
    description: str                   # 描述
    tool_names: List[str]              # 可用工具名列表
    system_prompt_template: str        # 系统提示词模板
    max_iterations: int = 20           # 最大迭代次数
    token_budget: Optional[TokenBudget] = None  # Token预算
    compression_strategy: str = "default"  # 压缩策略
    model_override: Optional[str] = None   # 模型覆盖
    can_delegate: bool = False         # 是否可以委派子任务
    delegation_targets: List[str] = field(default_factory=list)  # 可委派的Agent类型列表


class AgentFactory:
    """Agent工厂

    通过AgentTypeDefinition动态注册和创建Agent实例。
    """

    def __init__(self, global_registry: ToolRegistry):
        """初始化Agent工厂

        Args:
            global_registry: 全局工具注册表
        """
        self._agent_types: Dict[str, AgentTypeDefinition] = {}
        self._global_registry = global_registry

    def register_type(self, definition: AgentTypeDefinition) -> None:
        """注册Agent类型

        Args:
            definition: Agent类型定义
        """
        self._agent_types[definition.name] = definition
        logger.info(f"注册Agent类型: {definition.name} ({definition.display_name})")

    def create(
        self,
        agent_type: str,
        stream_manager: Optional['StreamManager'] = None
    ) -> AgentRuntime:
        """创建Agent实例

        Args:
            agent_type: Agent类型名称
            stream_manager: 流管理器（可选）

        Returns:
            AgentRuntime实例

        Raises:
            ValueError: 未知的Agent类型
        """
        if agent_type not in self._agent_types:
            raise ValueError(f"未知的Agent类型: {agent_type}")

        definition = self._agent_types[agent_type]

        # 解析工具子集
        tool_registry = self._resolve_tools(definition.tool_names)

        # 构建系统提示词
        system_prompt = self._build_system_prompt(definition)

        # 创建上下文管理器
        context_manager = ContextManager(
            token_budget=definition.token_budget or TokenBudget()
        )

        # 创建钩子系统
        hook_system = HookSystem()

        # 创建缓存
        cache = ToolResultCache()

        # 创建AgentRuntime
        agent = AgentRuntime(
            registry=tool_registry,
            max_iterations=definition.max_iterations,
            system_prompt=system_prompt,
            context_manager=context_manager,
            hook_system=hook_system,
            cache=cache
        )

        logger.info(f"创建Agent实例: {agent_type} | 工具数: {len(tool_registry.get_all_tools())}")

        return agent

    def _resolve_tools(self, tool_names: List[str]) -> ToolRegistry:
        """解析工具子集

        Args:
            tool_names: 工具名称列表

        Returns:
            工具注册表子集
        """
        registry = ToolRegistry()

        for tool_name in tool_names:
            tool = self._global_registry.get(tool_name)
            if tool:
                registry.register(tool)
            else:
                logger.warning(f"工具不存在: {tool_name}")

        return registry

    def _build_system_prompt(self, definition: AgentTypeDefinition) -> str:
        """构建系统提示词

        Args:
            definition: Agent类型定义

        Returns:
            系统提示词
        """
        # 基础模板
        base_template = definition.system_prompt_template

        # 注入上下文信息
        # 这里可以根据需要添加更多上下文

        return base_template

    def get_definition(self, agent_type: str) -> Optional[AgentTypeDefinition]:
        """获取Agent类型定义

        Args:
            agent_type: Agent类型名称

        Returns:
            Agent类型定义，如果不存在返回None
        """
        return self._agent_types.get(agent_type)

    def list_types(self) -> List[str]:
        """列出所有注册的Agent类型

        Returns:
            Agent类型名称列表
        """
        return list(self._agent_types.keys())
