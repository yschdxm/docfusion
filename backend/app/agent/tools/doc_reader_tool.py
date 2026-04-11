"""
文档阅读工具 - 让LLM能够阅读文档内容

功能：
- 获取文档基本信息
- 读取文档全文或指定部分
- 支持各种文档类型(docx, xlsx, md, txt等)
"""

from typing import Any, Dict
import os

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select


class DocReaderTool(BaseTool):
    """文档阅读工具

    让LLM能够阅读文档的内容，了解文档结构和信息。
    支持全文阅读或指定片段阅读。
    """

    MAX_CONTENT_LENGTH = 10000  # 最大返回内容长度

    @property
    def name(self) -> str:
        return "read_document"

    @property
    def description(self) -> str:
        return """阅读文档的内容，支持全文阅读或指定片段。

使用场景：
- 当需要了解文档的具体内容时
- 当RAG检索返回的片段不够完整时
- 当需要查看文档结构时

注意事项：
- 全文阅读可能返回大量内容，会被截断
- 建议优先使用rag_search进行信息检索
- 需要指定具体的文档ID"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "read_mode": {
                    "type": "string",
                    "enum": ["full", "head", "tail"],
                    "default": "head",
                    "description": "阅读模式: full(全文)、head(开头)、tail(结尾)"
                },
                "max_length": {
                    "type": "integer",
                    "default": 5000,
                    "description": "最大返回字符数，默认5000"
                }
            },
            "required": ["doc_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行文档阅读"""
        try:
            doc_id = params.get("doc_id", "")
            read_mode = params.get("read_mode", "head")
            max_length = min(params.get("max_length", 5000), self.MAX_CONTENT_LENGTH)

            if not doc_id:
                return ToolResult(
                    success=False,
                    error="文档ID不能为空"
                )

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == doc_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(
                        success=False,
                        error=f"文档不存在: {doc_id}"
                    )

                # 读取文档内容
                content = await self._read_doc_content(doc.file_path, read_mode, max_length)

                return ToolResult(
                    success=True,
                    data={
                        "doc_id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        "file_size": doc.file_size,
                        "read_mode": read_mode,
                        "content": content,
                        "truncated": len(content) >= max_length
                    },
                    metadata={
                        "doc_category": doc.doc_category,
                        "status": doc.status
                    }
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"文档阅读失败: {str(e)}"
            )

    async def _read_doc_content(
        self,
        file_path: str,
        read_mode: str,
        max_length: int
    ) -> str:
        """读取文档内容

        目前支持txt和md文件直接读取。
        其他格式返回提示信息。
        """
        try:
            if not os.path.exists(file_path):
                return f"[文件不存在: {file_path}]"

            # 检查文件扩展名
            ext = os.path.splitext(file_path)[1].lower()

            if ext in ['.txt', '.md']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                if read_mode == "head":
                    return content[:max_length]
                elif read_mode == "tail":
                    return content[-max_length:] if len(content) > max_length else content
                else:  # full
                    return content[:max_length]

            elif ext == '.docx':
                # 使用docx解析器
                try:
                    from docx import Document as DocxDocument
                    doc = DocxDocument(file_path)
                    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                    content = "\n".join(paragraphs)

                    if read_mode == "head":
                        return content[:max_length]
                    elif read_mode == "tail":
                        return content[-max_length:] if len(content) > max_length else content
                    else:
                        return content[:max_length]
                except Exception as e:
                    return f"[无法读取docx文件: {str(e)}]"

            elif ext == '.xlsx':
                # xlsx文件返回提示
                return "[这是Excel文件，建议使用query_pg_database查询结构化数据，或使用get_table_structure获取表格结构]"

            else:
                return f"[暂不支持的文件格式: {ext}，请使用rag_search进行内容检索]"

        except Exception as e:
            return f"[读取失败: {str(e)}]"
