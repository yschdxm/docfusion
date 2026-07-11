"""
Agent系统初始化

负责：
- 初始化AgentFactory
- 注册所有Agent类型
- 初始化SkillRegistry
- 注册所有Skill
- 创建AgentOrchestrator
"""

from typing import Optional
import logging

from app.agent.core.registry import ToolRegistry
from app.agent.core.factory import AgentFactory
from app.agent.core.orchestrator import AgentOrchestrator
from app.agent.core.delegation_manager import DelegationManager
from app.agent.core.skill_system import SkillRegistry, register_builtin_skills
from app.agent.tools import get_all_tools

logger = logging.getLogger(__name__)


def initialize_agent_system(
    global_registry: Optional[ToolRegistry] = None
) -> tuple:
    """初始化Agent系统

    Args:
        global_registry: 全局工具注册表（可选）

    Returns:
        (agent_factory, skill_registry, orchestrator) 元组
    """
    logger.info("开始初始化Agent系统...")

    # 1. 初始化全局工具注册表
    if global_registry is None:
        global_registry = ToolRegistry()
        tools = get_all_tools()
        global_registry.register_many(tools)
        logger.info(f"注册 {len(tools)} 个工具")

    # 2. 初始化AgentFactory
    agent_factory = AgentFactory(global_registry)

    # 3. 注册所有Agent类型
    from app.agent.agents import register_all_agents
    register_all_agents(agent_factory)
    logger.info(f"注册 {len(agent_factory.list_types())} 个Agent类型")

    # 4. 初始化SkillRegistry
    skill_registry = SkillRegistry()
    register_builtin_skills(skill_registry)
    logger.info(f"注册 {len(skill_registry.list_skills())} 个Skill")

    # 5. 初始化DelegationManager
    delegation_manager = DelegationManager(agent_factory)

    # 6. 初始化AgentOrchestrator
    orchestrator = AgentOrchestrator(agent_factory, delegation_manager)

    logger.info("Agent系统初始化完成")

    return agent_factory, skill_registry, orchestrator


# 全局实例
_agent_factory: Optional[AgentFactory] = None
_skill_registry: Optional[SkillRegistry] = None
_orchestrator: Optional[AgentOrchestrator] = None


def get_agent_factory() -> AgentFactory:
    """获取全局AgentFactory实例"""
    global _agent_factory
    if _agent_factory is None:
        _agent_factory, _, _ = initialize_agent_system()
    return _agent_factory


def get_skill_registry() -> SkillRegistry:
    """获取全局SkillRegistry实例"""
    global _skill_registry
    if _skill_registry is None:
        _, _skill_registry, _ = initialize_agent_system()
    return _skill_registry


def get_orchestrator() -> AgentOrchestrator:
    """获取全局AgentOrchestrator实例"""
    global _orchestrator
    if _orchestrator is None:
        _, _, _orchestrator = initialize_agent_system()
    return _orchestrator
