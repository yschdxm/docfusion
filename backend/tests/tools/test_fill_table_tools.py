"""
数据填写工具测试
"""

import pytest
from app.agent.tools.fill_table_tool import (
    FillTableTool,
    FillCellTool,
    FillRowTool,
    FillColumnTool,
    AutoFillSuggestionsTool
)
from app.agent.base.tool import ToolCategory, PermissionLevel


class TestFillTableTool:
    """FillTableTool 测试"""

    @pytest.fixture
    def tool(self):
        return FillTableTool()

    def test_name(self, tool):
        assert tool.name == "fill_table"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DATA_FILL

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SENSITIVE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 60000

    def test_cacheable(self, tool):
        assert tool.cacheable is True

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert "template_id" in params["properties"]
        assert "data" in params["properties"]
        assert "source_query" in params["properties"]


class TestFillCellTool:
    """FillCellTool 测试"""

    @pytest.fixture
    def tool(self):
        return FillCellTool()

    def test_name(self, tool):
        assert tool.name == "fill_cell"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DATA_FILL

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SENSITIVE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 5000

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert "file_id" in params["properties"]
        assert "row" in params["properties"]
        assert "col" in params["properties"]
        assert "value" in params["properties"]
        assert "file_id" in params["required"]
        assert "row" in params["required"]
        assert "col" in params["required"]
        assert "value" in params["required"]


class TestFillRowTool:
    """FillRowTool 测试"""

    @pytest.fixture
    def tool(self):
        return FillRowTool()

    def test_name(self, tool):
        assert tool.name == "fill_row"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DATA_FILL

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SENSITIVE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 10000


class TestFillColumnTool:
    """FillColumnTool 测试"""

    @pytest.fixture
    def tool(self):
        return FillColumnTool()

    def test_name(self, tool):
        assert tool.name == "fill_column"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DATA_FILL

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SENSITIVE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 10000


class TestAutoFillSuggestionsTool:
    """AutoFillSuggestionsTool 测试"""

    @pytest.fixture
    def tool(self):
        return AutoFillSuggestionsTool()

    def test_name(self, tool):
        assert tool.name == "auto_fill_suggestions"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DATA_FILL

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SAFE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 30000
