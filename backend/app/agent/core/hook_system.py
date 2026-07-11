"""
钩子系统 - 支持工具执行前后的自定义逻辑

功能：
- 工具执行前钩子（before_tool）
- 工具执行后钩子（after_tool）
- 工具错误钩子（on_error）
- 工具完成钩子（on_complete）
- 工具名模式匹配（通配符）
- 优先级排序
- 内置钩子
"""

import re
import logging
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from app.agent.base.tool import ToolResult

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    """钩子事件类型"""
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    ON_ERROR = "on_error"
    ON_COMPLETE = "on_complete"


@dataclass
class HookContext:
    """钩子上下文"""
    tool_name: str
    params: Dict[str, Any]
    result: Optional[ToolResult] = None
    error: Optional[Exception] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """钩子执行结果"""
    should_continue: bool = True  # 是否继续执行后续钩子和工具
    modified_params: Optional[Dict[str, Any]] = None  # 修改后的参数
    modified_result: Optional[ToolResult] = None  # 修改后的结果
    error: Optional[str] = None  # 错误信息


@dataclass
class HookDefinition:
    """钩子定义"""
    name: str
    event: HookEvent
    handler: Callable[[HookContext], Optional[HookResult]]
    tool_pattern: Optional[str] = None  # 工具名模式匹配，如 "query_*"
    priority: int = 0  # 越小越先执行
    enabled: bool = True


class HookSystem:
    """钩子系统

    支持工具执行前后的自定义逻辑。
    """

    def __init__(self):
        self._hooks: Dict[HookEvent, List[HookDefinition]] = {
            event: [] for event in HookEvent
        }
        self._enabled = True

    def register(self, hook: HookDefinition) -> None:
        """注册钩子

        Args:
            hook: 钩子定义
        """
        if hook.event not in self._hooks:
            self._hooks[hook.event] = []

        self._hooks[hook.event].append(hook)
        # 按优先级排序
        self._hooks[hook.event].sort(key=lambda h: h.priority)

        logger.info(f"注册钩子: {hook.name} ({hook.event.value})")

    def unregister(self, name: str) -> bool:
        """注销钩子

        Args:
            name: 钩子名称

        Returns:
            是否成功注销
        """
        for event, hooks in self._hooks.items():
            for i, hook in enumerate(hooks):
                if hook.name == name:
                    hooks.pop(i)
                    logger.info(f"注销钩子: {name}")
                    return True
        return False

    def _should_run_for_tool(self, hook: HookDefinition, tool_name: str) -> bool:
        """检查钩子是否应该对指定工具运行

        Args:
            hook: 钩子定义
            tool_name: 工具名称

        Returns:
            是否应该运行
        """
        if not hook.enabled:
            return False

        if hook.tool_pattern is None:
            return True

        # 支持通配符匹配
        pattern = hook.tool_pattern.replace("*", ".*")
        return bool(re.match(pattern, tool_name))

    async def execute_hooks(
        self,
        event: HookEvent,
        context: HookContext
    ) -> HookResult:
        """执行钩子链

        Args:
            event: 钩子事件类型
            context: 钩子上下文

        Returns:
            钩子执行结果
        """
        if not self._enabled:
            return HookResult(should_continue=True)

        hooks = self._hooks.get(event, [])
        final_result = HookResult(should_continue=True)

        for hook in hooks:
            if not self._should_run_for_tool(hook, context.tool_name):
                continue

            try:
                logger.debug(f"执行钩子: {hook.name} ({event.value})")
                result = await hook.handler(context)

                if result is None:
                    continue

                # 如果钩子要求停止，立即返回
                if not result.should_continue:
                    logger.info(f"钩子 {hook.name} 要求停止执行")
                    return result

                # 合并修改
                if result.modified_params is not None:
                    context.params = result.modified_params
                    final_result.modified_params = result.modified_params

                if result.modified_result is not None:
                    context.result = result.modified_result
                    final_result.modified_result = result.modified_result

            except Exception as e:
                logger.error(f"钩子 {hook.name} 执行失败: {e}")
                # 钩子失败不影响主流程
                continue

        return final_result

    async def before_tool(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> HookResult:
        """工具执行前钩子

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            钩子执行结果
        """
        context = HookContext(tool_name=tool_name, params=params)
        return await self.execute_hooks(HookEvent.BEFORE_TOOL, context)

    async def after_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: ToolResult
    ) -> HookResult:
        """工具执行后钩子

        Args:
            tool_name: 工具名称
            params: 工具参数
            result: 工具执行结果

        Returns:
            钩子执行结果
        """
        context = HookContext(
            tool_name=tool_name,
            params=params,
            result=result
        )
        return await self.execute_hooks(HookEvent.AFTER_TOOL, context)

    async def on_error(
        self,
        tool_name: str,
        params: Dict[str, Any],
        error: Exception
    ) -> HookResult:
        """工具错误钩子

        Args:
            tool_name: 工具名称
            params: 工具参数
            error: 异常

        Returns:
            钩子执行结果
        """
        context = HookContext(
            tool_name=tool_name,
            params=params,
            error=error
        )
        return await self.execute_hooks(HookEvent.ON_ERROR, context)

    async def on_complete(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: ToolResult
    ) -> HookResult:
        """工具完成钩子

        Args:
            tool_name: 工具名称
            params: 工具参数
            result: 工具执行结果

        Returns:
            钩子执行结果
        """
        context = HookContext(
            tool_name=tool_name,
            params=params,
            result=result
        )
        return await self.execute_hooks(HookEvent.ON_COMPLETE, context)

    def disable(self) -> None:
        """禁用钩子系统"""
        self._enabled = False
        logger.info("钩子系统已禁用")

    def enable(self) -> None:
        """启用钩子系统"""
        self._enabled = True
        logger.info("钩子系统已启用")

    def get_hooks(self, event: Optional[HookEvent] = None) -> List[HookDefinition]:
        """获取钩子列表

        Args:
            event: 钩子事件类型，如果为None则返回所有钩子

        Returns:
            钩子定义列表
        """
        if event:
            return self._hooks.get(event, [])
        return [h for hooks in self._hooks.values() for h in hooks]

    def get_hook_names(self) -> List[str]:
        """获取所有钩子名称

        Returns:
            钩子名称列表
        """
        return [h.name for h in self.get_hooks()]

    def is_enabled(self) -> bool:
        """检查钩子系统是否启用

        Returns:
            是否启用
        """
        return self._enabled


# 全局钩子系统实例
hook_system = HookSystem()
