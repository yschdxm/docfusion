"""
Agent路由系统

提供多Agent协作架构，包括通用Agent和专用Agent。
"""

from app.agent.agents.general_agent import create_general_agent
from app.agent.agents.fill_table_agent import FillTableAgent
from app.agent.agents.document_edit_agent import DocumentEditAgent

__all__ = [
    "create_general_agent",
    "FillTableAgent",
    "DocumentEditAgent",
]
