"""
文档处理 Agent

单一 Agent 架构：一个 Agent 持有全部工具，直接处理
填表、填表单、文档编辑、文档问答，无路由/委派层。
"""

from app.agent.agents.document_agent import create_document_agent

__all__ = [
    "create_document_agent",
]
