"""
文档读取工具测试
"""

import pytest
from app.agent.tools.doc_reader_tool import (
    DocReaderTool,
    ReadCellRangeTool,
    ReadSelectionTool,
    GetDocumentInfoTool,
    SearchInDocumentTool
)
from app.agent.base.tool import ToolCategory, PermissionLevel


class TestDocReaderTool:
    """DocReaderTool 测试"""

    @pytest.fixture
    def tool(self):
        return DocReaderTool()

    def test_name(self, tool):
        assert tool.name == "read_document"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DOCUMENT_READ

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SAFE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 10000

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert "doc_id" in params["properties"]
        assert "read_mode" in params["properties"]
        assert "doc_id" in params["required"]


class TestReadCellRangeTool:
    """ReadCellRangeTool 测试"""

    @pytest.fixture
    def tool(self):
        return ReadCellRangeTool()

    def test_name(self, tool):
        assert tool.name == "read_cell_range"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DOCUMENT_READ

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SAFE

    def test_cacheable(self, tool):
        assert tool.cacheable is True

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert "file_id" in params["properties"]
        assert "start_row" in params["properties"]
        assert "end_row" in params["properties"]
        assert "file_id" in params["required"]


class TestReadSelectionTool:
    """ReadSelectionTool 测试"""

    @pytest.fixture
    def tool(self):
        return ReadSelectionTool()

    def test_name(self, tool):
        assert tool.name == "read_selection"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DOCUMENT_READ

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SAFE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 5000


class TestGetDocumentInfoTool:
    """GetDocumentInfoTool 测试"""

    @pytest.fixture
    def tool(self):
        return GetDocumentInfoTool()

    def test_name(self, tool):
        assert tool.name == "get_document_info"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DOCUMENT_READ

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SAFE

    def test_cacheable(self, tool):
        assert tool.cacheable is True

    def test_timeout(self, tool):
        assert tool.timeout_ms == 5000


class TestSearchInDocumentTool:
    """SearchInDocumentTool 测试"""

    @pytest.fixture
    def tool(self):
        return SearchInDocumentTool()

    def test_name(self, tool):
        assert tool.name == "search_in_document"

    def test_category(self, tool):
        assert tool.category == ToolCategory.DOCUMENT_READ

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.SAFE

    def test_timeout(self, tool):
        assert tool.timeout_ms == 10000

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert "file_id" in params["properties"]
        assert "query" in params["properties"]
        assert "file_id" in params["required"]
        assert "query" in params["required"]
