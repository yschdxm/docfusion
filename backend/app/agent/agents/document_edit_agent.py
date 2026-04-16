"""
文档编辑专用Agent

处理文档内容和格式修改：文本替换、段落重写、标题调整、
样式设置、格式转换等。
"""

from typing import Any, Dict

from app.agent.core.delegation import DelegateAgentTool
from app.agent.core.registry import ToolRegistry
from app.agent.core.runtime import AgentRuntime
from app.agent.tools import RAGTool, DocReaderTool
from app.agent.tools.document_edit_tools import (
    ReplaceTextTool,
    RewriteParagraphTool,
    InsertAfterTool,
    HeadingPromoteTool,
    ListFormatTool,
    ParagraphSplitTool,
    SetTextStyleTool,
    ConvertTool,
)


DOCUMENT_EDIT_SYSTEM_PROMPT = """你是一个专业的文档编辑Agent，专注于处理文档内容和格式修改任务。

## 工作原则
1. 理解用户的编辑需求
2. 使用合适的工具执行编辑操作
3. 确保编辑结果符合用户要求
4. 向用户报告编辑结果

## 可用操作

### replace_text - 文本替换
替换文档中的指定文本。需要提供：
- file_id: 文档ID
- paragraph_index: 目标段落索引
- old_text: 要替换的原文本
- new_text: 替换后的新文本

### rewrite_paragraph - LLM重写段落
使用LLM重写指定段落。需要提供：
- file_id: 文档ID
- paragraph_index: 目标段落索引
- rewrite_instruction: 重写指令

### insert_after - 段落后插入
在指定段落后插入新内容。需要提供：
- file_id: 文档ID
- paragraph_index: 目标段落索引
- text: 要插入的文本

### heading_promote - 标题级别调整
调整标题级别。需要提供：
- file_id: 文档ID
- paragraph_index: 目标段落索引
- level: 目标级别（1-6）

### list_format - 列表格式化
将指定段落转换为列表格式。需要提供：
- file_id: 文档ID
- paragraph_indexes: 段落索引列表
- list_type: 列表类型（bullet/number）

### paragraph_split - 段落拆分
将长段落拆分为多个段落。需要提供：
- file_id: 文档ID
- paragraph_index: 目标段落索引
- separator: 分隔符（可选，默认按句号拆分）

### set_text_style - 字体样式设置
设置指定段落的字体样式。仅支持docx文件。需要提供：
- file_id: 文档ID
- paragraph_indexes: 段落索引列表
- font_name: 字体名称（可选）
- font_size_pt: 字体大小（pt，可选）

### convert - 格式转换
转换文档格式。支持：docx<->md, docx<->txt, md<->txt, xlsx->csv。需要提供：
- file_id: 文档ID
- target_format: 目标格式

## 工作流程
1. 使用 read_document 读取文档内容，了解文档结构
2. 根据用户指令选择合适的编辑操作
3. 执行编辑操作
4. 向用户报告编辑结果，包含下载链接

## 重要提醒
- 段落索引从0开始
- 编辑操作会生成新文件，原文件不会被修改
- 每次编辑后需要重新读取文档以获取最新内容
"""


class DocumentEditAgent(DelegateAgentTool):
    """文档编辑专用Agent

    处理文档内容和格式修改：文本替换、段落重写、标题调整、
    样式设置、格式转换等。
    """

    @property
    def name(self) -> str:
        return "delegate_document_edit"

    @property
    def description(self) -> str:
        return "将文档编辑任务委派给专用的文档编辑Agent。当用户需要修改文档内容、调整格式、重写段落、转换格式时使用此工具。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "文档编辑任务描述"
                },
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要编辑的文档ID列表"
                },
            },
            "required": ["task_description", "file_ids"]
        }

    def _create_agent(self) -> AgentRuntime:
        """创建文档编辑专用Agent"""
        registry = ToolRegistry()
        registry.register(DocReaderTool())  # 读取文档内容
        registry.register(RAGTool())        # 搜索定位内容
        # 注册文档编辑工具
        registry.register(ReplaceTextTool())
        registry.register(RewriteParagraphTool())
        registry.register(InsertAfterTool())
        registry.register(HeadingPromoteTool())
        registry.register(ListFormatTool())
        registry.register(ParagraphSplitTool())
        registry.register(SetTextStyleTool())
        registry.register(ConvertTool())
        # 不注册填表相关工具
        # 不注册 DelegateAgentTool

        return AgentRuntime(
            registry,
            max_iterations=20,
            system_prompt=DOCUMENT_EDIT_SYSTEM_PROMPT,
        )

    def _extract_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从子Agent结果中提取文档编辑特有信息"""
        return {
            "output_file": result.get("output_file"),
            "download_url": result.get("download_url"),
            "changes": result.get("changes", []),
        }
