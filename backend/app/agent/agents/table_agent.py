"""
TableAgent - 表格填写Agent

职责：
- 模板表格结构分析
- 数据填写
- 智能填充
"""

from typing import Dict, Any
import logging

from app.agent.core.factory import AgentTypeDefinition

logger = logging.getLogger(__name__)


TABLE_SYSTEM_PROMPT = """你是一个专业的表格填写助手。

## 职责
1. 分析表格结构
2. 查询填写数据
3. 填写表格
4. 智能填充建议

## 工具使用指南
- get_table_structure: 获取表格结构
- fill_table: 填写表格
- fill_cell: 填写单个单元格
- fill_row: 填写整行
- fill_column: 填写整列
- auto_fill_suggestions: 智能填充建议
- query_pg_database: 查询PostgreSQL数据库
- query_knowledge_graph: 查询Neo4j知识图谱
- rag_search: RAG向量检索

## 填表流程
1. 获取表格结构，了解列名和数据类型
2. 查询数据源，获取填写数据
3. 填写表格，注意数据格式匹配
4. 检查填写结果，确保完整性

## 工作原则
1. 先了解表格结构再填写
2. 数据格式要与列类型匹配
3. 大数据量使用批量填写
4. 填写后检查数据完整性"""


def get_table_definition() -> AgentTypeDefinition:
    """获取TableAgent类型定义"""
    return AgentTypeDefinition(
        name="table",
        display_name="表格填写Agent",
        description="模板表格结构分析、数据填写",
        tool_names=[
            "get_table_structure", "fill_table", "fill_cell",
            "fill_row", "fill_column", "auto_fill_suggestions",
            "query_pg_database", "query_knowledge_graph",
            "rag_search"
        ],
        system_prompt_template=TABLE_SYSTEM_PROMPT,
        max_iterations=20,
        can_delegate=False
    )
