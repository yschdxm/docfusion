"""
DataAgent - 数据处理Agent

职责：
- 数据查询
- 数据提取
- 统计分析
"""

from typing import Dict, Any
import logging

from app.agent.core.factory import AgentTypeDefinition

logger = logging.getLogger(__name__)


DATA_SYSTEM_PROMPT = """你是一个专业的数据处理助手。

## 职责
1. 查询结构化数据
2. 提取关键信息
3. 进行统计分析

## 数据源
- PostgreSQL: xlsx结构化数据
- Neo4j: 实体关系数据
- RAG: 非结构化文本

## 工具使用指南
- query_pg_database: 查询PostgreSQL数据库
- query_knowledge_graph: 查询Neo4j知识图谱
- natural_language_query: 自然语言查询（自动路由）
- aggregate_data: 数据聚合统计
- rag_search: RAG向量检索
- read_document: 读取文档内容

## 数据源选择规则
1. xlsx文件 → 优先使用query_pg_database
2. docx/md/txt文件 → 使用query_knowledge_graph
3. 不确定时 → 使用natural_language_query

## 工作原则
1. 优先使用结构化数据源
2. 查询失败时尝试其他数据源
3. 大数据量使用聚合统计
4. 返回结构化结果"""


def get_data_definition() -> AgentTypeDefinition:
    """获取DataAgent类型定义"""
    return AgentTypeDefinition(
        name="data",
        display_name="数据处理Agent",
        description="数据查询、提取、统计分析",
        tool_names=[
            "query_pg_database", "query_knowledge_graph",
            "natural_language_query", "aggregate_data",
            "rag_search", "read_document"
        ],
        system_prompt_template=DATA_SYSTEM_PROMPT,
        max_iterations=15,
        can_delegate=False
    )
