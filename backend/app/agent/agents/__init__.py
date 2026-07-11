"""
Agent路由系统

提供多Agent协作架构，包括通用Agent和专用Agent。
"""

# 现有Agent
from app.agent.agents.general_agent import create_general_agent
from app.agent.agents.fill_table_agent import FillTableAgent
from app.agent.agents.document_edit_agent import DocumentEditAgent

# 新增Agent
from app.agent.agents.planner_agent import PlannerAgent
from app.agent.agents.editor_agent import get_editor_definition
from app.agent.agents.data_agent import get_data_definition
from app.agent.agents.knowledge_agent import get_knowledge_definition
from app.agent.agents.table_agent import get_table_definition
from app.agent.agents.search_agent import get_search_definition

__all__ = [
    # 现有Agent
    "create_general_agent",
    "FillTableAgent",
    "DocumentEditAgent",
    # 新增Agent
    "PlannerAgent",
    "get_editor_definition",
    "get_data_definition",
    "get_knowledge_definition",
    "get_table_definition",
    "get_search_definition",
]


def register_all_agents(agent_factory: 'AgentFactory') -> None:
    """注册所有Agent类型

    Args:
        agent_factory: Agent工厂
    """
    # 注册专业Agent
    agent_factory.register_type(get_editor_definition())
    agent_factory.register_type(get_data_definition())
    agent_factory.register_type(get_knowledge_definition())
    agent_factory.register_type(get_table_definition())
    agent_factory.register_type(get_search_definition())

    print(f"已注册 {len(agent_factory.list_types())} 个Agent类型")
