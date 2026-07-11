"""
SearchAgent - 搜索检索Agent

职责：
- 跨文档搜索
- RAG检索
- 信息定位
"""

from typing import Dict, Any
import logging

from app.agent.core.factory import AgentTypeDefinition

logger = logging.getLogger(__name__)


SEARCH_SYSTEM_PROMPT = """你是一个专业的搜索检索助手。

## 职责
1. 跨文档搜索
2. RAG向量检索
3. 信息定位

## 工具使用指南
- search_documents: 跨文档搜索
- rag_search: RAG向量检索
- web_search: 网络搜索
- search_in_document: 在文档中搜索
- read_document: 读取文档内容
- get_document_info: 获取文档元数据

## 搜索模式
- keyword: 关键词匹配，速度快
- semantic: 语义检索，适合模糊搜索
- hybrid: 结合两种方式，效果最好

## 工作原则
1. 优先使用hybrid模式
2. 结果要包含上下文
3. 多文档搜索要汇总
4. 返回相关性排序的结果"""


def get_search_definition() -> AgentTypeDefinition:
    """获取SearchAgent类型定义"""
    return AgentTypeDefinition(
        name="search",
        display_name="搜索检索Agent",
        description="跨文档搜索、RAG检索、信息定位",
        tool_names=[
            "search_documents", "rag_search", "web_search",
            "search_in_document", "read_document", "get_document_info"
        ],
        system_prompt_template=SEARCH_SYSTEM_PROMPT,
        max_iterations=10,
        can_delegate=False
    )
