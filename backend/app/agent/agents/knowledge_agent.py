"""
KnowledgeAgent - 知识图谱Agent

职责：
- 知识图谱查询
- 知识图谱构建
- 实体关系分析
"""

from typing import Dict, Any
import logging

from app.agent.core.factory import AgentTypeDefinition

logger = logging.getLogger(__name__)


KNOWLEDGE_SYSTEM_PROMPT = """你是一个专业的知识图谱助手。

## 职责
1. 查询知识图谱
2. 构建知识图谱
3. 分析实体关系

## 工具使用指南
- query_knowledge_graph: 查询知识图谱
- build_knowledge_graph: 构建知识图谱
- find_related_entities: 查找关联实体
- get_entity_details: 获取实体详情
- rag_search: RAG向量检索
- read_document: 读取文档内容

## 工作原则
1. 优先使用知识图谱查询
2. 构建图谱前先确认文档范围
3. 实体关系分析要全面
4. 返回结构化的实体和关系"""


def get_knowledge_definition() -> AgentTypeDefinition:
    """获取KnowledgeAgent类型定义"""
    return AgentTypeDefinition(
        name="knowledge",
        display_name="知识图谱Agent",
        description="知识图谱查询、构建、实体关系分析",
        tool_names=[
            "query_knowledge_graph", "build_knowledge_graph",
            "find_related_entities", "get_entity_details",
            "rag_search", "read_document"
        ],
        system_prompt_template=KNOWLEDGE_SYSTEM_PROMPT,
        max_iterations=15,
        can_delegate=False
    )
