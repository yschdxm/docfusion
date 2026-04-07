"""
Agent基础组件模块

包含工具基类、上下文、结果定义
"""

from .tool import BaseTool, ToolContext, ToolResult

__all__ = ["BaseTool", "ToolContext", "ToolResult"]
