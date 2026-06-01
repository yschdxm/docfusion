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
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_index: 目标段落索引
- old_text: 要替换的原文本
- new_text: 替换后的新文本

### rewrite_paragraph - LLM重写段落
使用LLM重写指定段落。需要提供：
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_index: 目标段落索引
- rewrite_instruction: 重写指令

### insert_after - 段落后插入
在指定段落后插入新内容。需要提供：
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_index: 目标段落索引
- text: 要插入的文本

### heading_promote - 标题级别调整
调整标题级别。需要提供：
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_index: 目标段落索引
- level: 目标级别（1-6）

### list_format - 列表格式化
将指定段落转换为列表格式。需要提供：
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_indexes: 段落索引列表
- list_type: 列表类型（bullet/number）

### paragraph_split - 段落拆分
将长段落拆分为多个段落。需要提供：
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_index: 目标段落索引
- separator: 分隔符（可选，默认按句号拆分）

### set_text_style - 字体样式设置
设置指定段落的字体样式。仅支持docx文件。需要提供：
- file_id: 文档ID（首次用原始ID，后续用上一步返回的output_file_id）
- paragraph_indexes: 段落索引列表
- font_name: 字体名称（可选）
- font_size_pt: 字体大小（pt，可选）

### convert - 格式转换
转换文档格式。支持：docx<->md, docx<->txt, md<->txt, xlsx->csv。需要提供：
- file_id: 文档ID
- target_format: 目标格式

## 工作流程
1. 使用 read_document 读取文档内容，了解文档结构
2. 根据用户指令选择合适的编辑操作（首次编辑：file_id=原始文档ID）
3. 收到编辑结果后，记住返回的 output_file_id，后续对该文档的编辑使用 file_id=output_file_id
4. 向用户报告编辑结果

## 报告结果（必须严格遵守）

向用户报告编辑结果时，**必须包含以下所有内容，缺一不可**：

1. **修改说明**：简要说明对文档做了哪些修改
2. **下载链接（必须输出可点击链接）**：
   - 使用最后一次编辑工具返回的 `download_url` 字段
   - 格式：`[点击下载编辑后的文档](download_url)`
   - **必须使用标准 Markdown 链接格式 `[文字](URL)`**
   - **download_url 必须使用工具返回的相对路径（如 `/api/v1/documents/xxx/download`），禁止添加域名前缀**
   - **绝对禁止**自行编造完整URL（如 `https://xxx.com/api/v1/...`），系统会自动解析域名
   - **禁止省略下载链接，禁止只写纯文本URL，禁止写"您可以下载查看"却不给链接**

## 示例：连续编辑工作流

```
步骤1: replace_text(file_id="原始文档ID", paragraph_index=0, old_text="旧文本", new_text="新文本")
→ 返回 output_file_id="ABC123", download_url="/api/v1/documents/ABC123/download"

步骤2: rewrite_paragraph(file_id="ABC123", paragraph_index=1, rewrite_instruction="更正式")
→ 返回 output_file_id="ABC123", download_url="/api/v1/documents/ABC123/download"

步骤3: 向用户报告：[点击下载编辑后的文档](/api/v1/documents/ABC123/download)
```

## 重要规则
- 段落索引从0开始
- 原始文件不会被修改，每次编辑都在副本上进行
- **连续编辑同一文档时，记住 output_file_id，后续编辑传入 file_id=output_file_id**
- 每次编辑后段落索引不变（因为是在同一个文件上修改）
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
