"""
ToolRegistry 测试
"""

import pytest
from app.agent.core.registry import ToolRegistry
from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel


class MockTool(BaseTool):
    """模拟工具"""

    @property
    def name(self):
        return "mock_tool"

    @property
    def description(self):
        return "Mock tool for testing"

    @property
    def category(self):
        return ToolCategory.SYSTEM

    @property
    def permission_level(self):
        return PermissionLevel.SAFE

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, params, context):
        return ToolResult(success=True, data={"result": "ok"})


class MockTool2(BaseTool):
    """模拟工具2"""

    @property
    def name(self):
        return "mock_tool_2"

    @property
    def description(self):
        return "Mock tool 2 for testing"

    @property
    def category(self):
        return ToolCategory.DATA_QUERY

    @property
    def permission_level(self):
        return PermissionLevel.SENSITIVE

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, params, context):
        return ToolResult(success=True, data={"result": "ok"})


class TestToolRegistry:
    """ToolRegistry 测试"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def mock_tool(self):
        return MockTool()

    @pytest.fixture
    def mock_tool2(self):
        return MockTool2()

    def test_register(self, registry, mock_tool):
        registry.register(mock_tool)
        assert "mock_tool" in registry.list_tools()

    def test_register_many(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        assert "mock_tool" in registry.list_tools()
        assert "mock_tool_2" in registry.list_tools()

    def test_get(self, registry, mock_tool):
        registry.register(mock_tool)
        tool = registry.get("mock_tool")
        assert tool is not None
        assert tool.name == "mock_tool"

    def test_get_nonexistent(self, registry):
        tool = registry.get("nonexistent")
        assert tool is None

    def test_unregister(self, registry, mock_tool):
        registry.register(mock_tool)
        registry.unregister("mock_tool")
        assert "mock_tool" not in registry.list_tools()

    def test_list_tools(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        tools = registry.list_tools()
        assert len(tools) == 2
        assert "mock_tool" in tools
        assert "mock_tool_2" in tools

    def test_allow_list(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        registry.set_allow_list(["mock_tool"])
        assert registry.is_tool_allowed("mock_tool") is True
        assert registry.is_tool_allowed("mock_tool_2") is False

    def test_deny_list(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        registry.set_deny_list(["mock_tool"])
        assert registry.is_tool_allowed("mock_tool") is False
        assert registry.is_tool_allowed("mock_tool_2") is True

    def test_clear_lists(self, registry, mock_tool):
        registry.register(mock_tool)
        registry.set_allow_list(["mock_tool"])
        registry.clear_lists()
        assert registry.is_tool_allowed("mock_tool") is True

    def test_list_tools_by_category(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        system_tools = registry.list_tools_by_category(ToolCategory.SYSTEM)
        assert "mock_tool" in system_tools
        assert "mock_tool_2" not in system_tools

    def test_list_tools_by_permission(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        safe_tools = registry.list_tools_by_permission(PermissionLevel.SAFE)
        assert "mock_tool" in safe_tools
        assert "mock_tool_2" not in safe_tools

    def test_get_safe_tools(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        safe_tools = registry.get_safe_tools()
        assert len(safe_tools) == 1
        assert safe_tools[0].name == "mock_tool"

    def test_get_sensitive_tools(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        sensitive_tools = registry.get_sensitive_tools()
        assert len(sensitive_tools) == 1
        assert sensitive_tools[0].name == "mock_tool_2"

    def test_get_statistics(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        stats = registry.get_statistics()
        assert stats["total"] == 2
        assert stats["by_category"]["system"] == 1
        assert stats["by_category"]["data_query"] == 1
        assert stats["by_permission"]["safe"] == 1
        assert stats["by_permission"]["sensitive"] == 1

    def test_contains(self, registry, mock_tool):
        registry.register(mock_tool)
        assert "mock_tool" in registry
        assert "nonexistent" not in registry

    def test_len(self, registry, mock_tool, mock_tool2):
        registry.register_many([mock_tool, mock_tool2])
        assert len(registry) == 2
