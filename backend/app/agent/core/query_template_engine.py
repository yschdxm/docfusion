"""
查询模板引擎 - 替代LLM生成SQL

负责：
- 预编译查询模板
- 根据意图构建查询
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class QueryTemplate:
    """查询模板"""
    name: str
    description: str
    template: str
    parameters: List[str]


@dataclass
class QueryIntent:
    """查询意图"""
    pattern: str  # "get_all_records", "aggregate_by_column", "lookup_by_key"
    columns: Optional[List[str]] = None
    where: Optional[Dict[str, Any]] = None
    group_by: Optional[str] = None
    aggregate_function: Optional[str] = None
    limit: Optional[int] = None


class QueryTemplateEngine:
    """查询模板引擎

    通过预编译模板替代LLM生成SQL。
    """

    # 预编译模板
    TEMPLATES = {
        "get_all_records": QueryTemplate(
            name="get_all_records",
            description="获取所有记录",
            template="SELECT {columns} FROM {table} {where} {order_by} {limit}",
            parameters=["columns", "table", "where", "order_by", "limit"]
        ),
        "aggregate_by_column": QueryTemplate(
            name="aggregate_by_column",
            description="按列聚合",
            template="SELECT {group_by}, {aggregate_function}({column}) as result FROM {table} {where} GROUP BY {group_by}",
            parameters=["group_by", "aggregate_function", "column", "table", "where"]
        ),
        "lookup_by_key": QueryTemplate(
            name="lookup_by_key",
            description="按键查找",
            template="SELECT {columns} FROM {table} WHERE {key} = '{value}'",
            parameters=["columns", "table", "key", "value"]
        ),
    }

    def build_query(
        self,
        intent: QueryIntent,
        table_info: Dict[str, Any]
    ) -> str:
        """构建查询

        Args:
            intent: 查询意图
            table_info: 表信息

        Returns:
            SQL查询
        """
        # 选择模板
        template = self.TEMPLATES.get(intent.pattern)
        if not template:
            raise ValueError(f"未知的查询模式: {intent.pattern}")

        # 构建参数
        params = {
            "table": table_info.get("table_name", "data"),
            "columns": self._resolve_columns(intent.columns, table_info),
            "where": self._build_where(intent.where),
            "order_by": "",
            "limit": f"LIMIT {intent.limit}" if intent.limit else "",
            "group_by": intent.group_by or "",
            "aggregate_function": intent.aggregate_function or "COUNT",
            "column": intent.columns[0] if intent.columns else "*",
            "key": "",
            "value": "",
        }

        # 填充模板
        query = template.template.format(**params)

        # 清理多余空格
        query = " ".join(query.split())

        return query

    def _resolve_columns(
        self,
        columns: Optional[List[str]],
        table_info: Dict[str, Any]
    ) -> str:
        """解析列名"""
        if columns:
            return ", ".join(columns)
        return "*"

    def _build_where(self, where: Optional[Dict[str, Any]]) -> str:
        """构建WHERE子句"""
        if not where:
            return ""

        conditions = []
        for key, value in where.items():
            if isinstance(value, str):
                conditions.append(f"{key} = '{value}'")
            else:
                conditions.append(f"{key} = {value}")

        return "WHERE " + " AND ".join(conditions)


# 全局查询模板引擎实例
query_template_engine = QueryTemplateEngine()
