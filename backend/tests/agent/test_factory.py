"""
AgentFactory 测试
"""

import pytest
from app.agent.core.factory import AgentFactory, AgentTypeDefinition
from app.agent.core.registry import ToolRegistry


class TestAgentFactory:
    """AgentFactory 测试"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def factory(self, registry):
        return AgentFactory(registry)

    def test_register_type(self, factory):
        definition = AgentTypeDefinition(
            name="test_agent",
            display_name="Test Agent",
            description="A test agent",
            tool_names=[],
            system_prompt_template="You are a test agent."
        )
        factory.register_type(definition)
        assert "test_agent" in factory.list_types()

    def test_register_multiple_types(self, factory):
        for i in range(3):
            definition = AgentTypeDefinition(
                name=f"agent_{i}",
                display_name=f"Agent {i}",
                description=f"Agent {i}",
                tool_names=[],
                system_prompt_template=f"You are agent {i}."
            )
            factory.register_type(definition)

        assert len(factory.list_types()) == 3

    def test_create_agent(self, factory):
        definition = AgentTypeDefinition(
            name="test_agent",
            display_name="Test Agent",
            description="A test agent",
            tool_names=[],
            system_prompt_template="You are a test agent.",
            max_iterations=10
        )
        factory.register_type(definition)

        agent = factory.create("test_agent")
        assert agent is not None
        assert agent.max_iterations == 10

    def test_create_unknown_type(self, factory):
        with pytest.raises(ValueError, match="未知的Agent类型"):
            factory.create("unknown")

    def test_get_definition(self, factory):
        definition = AgentTypeDefinition(
            name="test_agent",
            display_name="Test Agent",
            description="A test agent",
            tool_names=[],
            system_prompt_template="You are a test agent."
        )
        factory.register_type(definition)

        result = factory.get_definition("test_agent")
        assert result is not None
        assert result.name == "test_agent"
        assert result.display_name == "Test Agent"

    def test_get_definition_nonexistent(self, factory):
        result = factory.get_definition("nonexistent")
        assert result is None

    def test_list_types(self, factory):
        assert len(factory.list_types()) == 0

        definition = AgentTypeDefinition(
            name="test_agent",
            display_name="Test Agent",
            description="A test agent",
            tool_names=[],
            system_prompt_template="You are a test agent."
        )
        factory.register_type(definition)

        types = factory.list_types()
        assert "test_agent" in types
