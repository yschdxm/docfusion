"""
内置钩子实现

提供常用的钩子：
- input_sanitizer: 输入清理钩子 - 清理工具参数中的潜在注入内容
- result_logger: 结果记录钩子 - 记录工具执行结果到审计日志
- token_tracker: Token追踪钩子 - 更新Token使用统计
- error_enricher: 错误丰富钩子 - 丰富错误信息，隐藏内部路径
"""

import logging
from typing import Optional

from app.agent.core.hook_system import (
    HookDefinition,
    HookEvent,
    HookContext,
    HookResult,
    hook_system
)

logger = logging.getLogger(__name__)


async def input_sanitizer_handler(context: HookContext) -> HookResult:
    """输入清理钩子 - 清理工具参数中的潜在注入内容

    Args:
        context: 钩子上下文

    Returns:
        钩子执行结果
    """
    params = context.params.copy()
    modified = False

    # 清理字符串参数中的危险字符
    for key, value in params.items():
        if isinstance(value, str):
            # 移除可能导致注入的字符
            original = value
            value = value.replace("\\", "").replace(";", "").replace("&", "")
            if value != original:
                params[key] = value
                modified = True

    if modified:
        logger.debug(f"输入清理: {context.tool_name}")
        return HookResult(modified_params=params)

    return HookResult()


async def result_logger_handler(context: HookContext) -> HookResult:
    """结果记录钩子 - 记录工具执行结果到审计日志

    Args:
        context: 钩子上下文

    Returns:
        钩子执行结果
    """
    if context.result:
        logger.info(
            f"工具执行完成 | {context.tool_name} | "
            f"成功: {context.result.success} | "
            f"耗时: {context.result.execution_time_ms}ms"
        )

        # 记录详细结果（仅在调试模式）
        if logger.isEnabledFor(logging.DEBUG):
            if context.result.data:
                import json
                data_preview = json.dumps(
                    context.result.data,
                    ensure_ascii=False,
                    default=str
                )[:200]
                logger.debug(f"工具结果预览: {data_preview}...")

    return HookResult()


async def token_tracker_handler(context: HookContext) -> HookResult:
    """Token追踪钩子 - 更新Token使用统计

    Args:
        context: 钩子上下文

    Returns:
        钩子执行结果
    """
    # 这里可以集成到统计数据系统
    # 目前只是记录日志
    if context.result and context.result.execution_time_ms > 0:
        logger.debug(
            f"Token追踪 | {context.tool_name} | "
            f"执行时间: {context.result.execution_time_ms}ms"
        )

    return HookResult()


async def error_enricher_handler(context: HookContext) -> HookResult:
    """错误丰富钩子 - 丰富错误信息，隐藏内部路径

    Args:
        context: 钩子上下文

    Returns:
        钩子执行结果
    """
    if context.error:
        error_msg = str(context.error)

        # 隐藏内部路径
        error_msg = error_msg.replace("/home/", "~/")
        error_msg = error_msg.replace("\\Users\\", "~\\")

        # 隐藏敏感信息
        error_msg = error_msg.replace("password", "***")
        error_msg = error_msg.replace("token", "***")
        error_msg = error_msg.replace("secret", "***")

        logger.warning(f"工具错误 | {context.tool_name} | {error_msg}")
        return HookResult(error=error_msg)

    return HookResult()


# 内置钩子定义
input_sanitizer = HookDefinition(
    name="input_sanitizer",
    event=HookEvent.BEFORE_TOOL,
    handler=input_sanitizer_handler,
    priority=0,
    enabled=True
)

result_logger = HookDefinition(
    name="result_logger",
    event=HookEvent.AFTER_TOOL,
    handler=result_logger_handler,
    priority=100,
    enabled=True
)

token_tracker = HookDefinition(
    name="token_tracker",
    event=HookEvent.AFTER_TOOL,
    handler=token_tracker_handler,
    priority=50,
    enabled=True
)

error_enricher = HookDefinition(
    name="error_enricher",
    event=HookEvent.ON_ERROR,
    handler=error_enricher_handler,
    priority=0,
    enabled=True
)


def register_builtin_hooks() -> None:
    """注册所有内置钩子

    将内置钩子注册到全局钩子系统。
    """
    hook_system.register(input_sanitizer)
    hook_system.register(result_logger)
    hook_system.register(token_tracker)
    hook_system.register(error_enricher)

    logger.info("内置钩子已注册")
