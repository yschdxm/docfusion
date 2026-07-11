"""
QueryTemplateEngine 测试
"""

import pytest
from app.agent.core.query_template_engine import QueryTemplateEngine, QueryIntent


class TestQueryTemplateEngine:
    """QueryTemplateEngine 测试"""

    @pytest.fixture
    def engine(self):
        return QueryTemplateEngine()

    def test_build_get_all_records(self, engine):
        intent = QueryIntent(
            pattern="get_all_records",
            columns=["name", "age"],
            limit=100
        )
        table_info = {"table_name": "users"}

        query = engine.build_query(intent, table_info)
        assert "SELECT name, age FROM users" in query
        assert "LIMIT 100" in query

    def test_build_get_all_records_all_columns(self, engine):
        intent = QueryIntent(
            pattern="get_all_records"
        )
        table_info = {"table_name": "users"}

        query = engine.build_query(intent, table_info)
        assert "SELECT * FROM users" in query

    def test_build_aggregate(self, engine):
        intent = QueryIntent(
            pattern="aggregate_by_column",
            columns=["salary"],
            group_by="department",
            aggregate_function="AVG"
        )
        table_info = {"table_name": "employees"}

        query = engine.build_query(intent, table_info)
        assert "AVG(salary)" in query
        assert "GROUP BY department" in query

    def test_build_lookup(self, engine):
        intent = QueryIntent(
            pattern="lookup_by_key",
            columns=["*"],
            where={"id": 123}
        )
        table_info = {"table_name": "users"}

        query = engine.build_query(intent, table_info)
        assert "WHERE id = 123" in query

    def test_build_lookup_string_value(self, engine):
        intent = QueryIntent(
            pattern="lookup_by_key",
            columns=["*"],
            where={"name": "John"}
        )
        table_info = {"table_name": "users"}

        query = engine.build_query(intent, table_info)
        assert "WHERE name = 'John'" in query

    def test_unknown_pattern(self, engine):
        intent = QueryIntent(pattern="unknown")
        table_info = {"table_name": "users"}

        with pytest.raises(ValueError, match="未知的查询模式"):
            engine.build_query(intent, table_info)

    def test_templates_registered(self, engine):
        assert "get_all_records" in engine.TEMPLATES
        assert "aggregate_by_column" in engine.TEMPLATES
        assert "lookup_by_key" in engine.TEMPLATES

    def test_resolve_columns(self, engine):
        # 指定列
        columns = engine._resolve_columns(["col1", "col2"], {})
        assert columns == "col1, col2"

        # 不指定列
        columns = engine._resolve_columns(None, {})
        assert columns == "*"

    def test_build_where(self, engine):
        # 空条件
        where = engine._build_where(None)
        assert where == ""

        # 单条件
        where = engine._build_where({"id": 123})
        assert where == "WHERE id = 123"

        # 多条件
        where = engine._build_where({"id": 123, "name": "John"})
        assert "WHERE" in where
        assert "id = 123" in where
        assert "name = 'John'" in where
