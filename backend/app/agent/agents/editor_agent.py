"""
EditorAgent - 文档编辑Agent

职责：
- 文档内容读取
- 文档编辑
- 格式调整
- 格式转换
"""

from typing import Dict, Any
import logging

from app.agent.core.factory import AgentTypeDefinition

logger = logging.getLogger(__name__)


EDITOR_SYSTEM_PROMPT = """你是一个专业的文档编辑助手。

## 职责
1. 读取文档内容
2. 编辑文档内容
3. 调整文档格式
4. 转换文档格式

## 工具使用指南
- read_document: 读取文档内容
- read_cell_range: 读取Excel指定范围
- read_selection: 读取用户选中内容
- get_document_info: 获取文档元数据
- search_in_document: 在文档中搜索
- replace_text: 替换文本
- rewrite_paragraph: 重写段落
- insert_content: 插入内容
- delete_content: 删除内容
- batch_edit: 批量编辑
- set_text_style: 设置文本样式
- heading_promote: 调整标题级别
- list_format: 列表格式化
- paragraph_split: 段落拆分
- convert: 格式转换
- export_document: 导出文档

## 工作原则
1. 保持文档原有格式
2. 编辑前先备份
3. 批量操作使用batch_edit
4. 格式转换前确认用户需求"""


def get_editor_definition() -> AgentTypeDefinition:
    """获取EditorAgent类型定义"""
    return AgentTypeDefinition(
        name="editor",
        display_name="文档编辑Agent",
        description="文档内容读取、编辑、格式调整、转换",
        tool_names=[
            "read_document", "read_cell_range", "read_selection",
            "get_document_info", "search_in_document",
            "replace_text", "rewrite_paragraph", "insert_content",
            "delete_content", "batch_edit", "set_text_style",
            "heading_promote", "list_format", "paragraph_split",
            "convert", "export_document"
        ],
        system_prompt_template=EDITOR_SYSTEM_PROMPT,
        max_iterations=20,
        can_delegate=False
    )
