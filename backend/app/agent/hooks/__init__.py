"""
内置钩子模块

提供常用的钩子实现：
- input_sanitizer: 输入清理钩子
- result_logger: 结果记录钩子
- token_tracker: Token追踪钩子
- error_enricher: 错误丰富钩子
"""

from .builtin_hooks import (
    input_sanitizer,
    result_logger,
    token_tracker,
    error_enricher,
    register_builtin_hooks
)

__all__ = [
    "input_sanitizer",
    "result_logger",
    "token_tracker",
    "error_enricher",
    "register_builtin_hooks"
]
