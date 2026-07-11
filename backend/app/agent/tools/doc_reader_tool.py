"""
文档阅读工具 - 让LLM能够阅读文档内容

功能：
- 获取文档基本信息
- 读取文档全文或指定部分
- 读取Excel指定范围的单元格数据
- 读取用户在编辑器中选中的内容
- 在文档中搜索文本
- 支持各种文档类型(docx, xlsx, md, txt等)
"""

from typing import Any, Dict, List, Optional
import os
import re

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel
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
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_READ

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 10000  # 10秒

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


class ReadCellRangeTool(BaseTool):
    """读取Excel指定范围的单元格数据"""

    @property
    def name(self) -> str:
        return "read_cell_range"

    @property
    def description(self) -> str:
        return """读取Excel文件指定范围的单元格数据。

使用场景：
- 当需要读取Excel表格的特定区域时
- 当需要获取表格的部分数据时
- 当query_pg_database返回的数据不够精确时

注意事项：
- 行和列索引从0开始
- end_row和end_col是包含的（闭区间）
- 建议指定sheet_name，否则使用第一个工作表"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_READ

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 10000  # 10秒

    @property
    def cacheable(self) -> bool:
        return True

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（可选，默认第一个）"
                },
                "start_row": {
                    "type": "integer",
                    "description": "起始行（从0开始）"
                },
                "end_row": {
                    "type": "integer",
                    "description": "结束行（包含）"
                },
                "start_col": {
                    "type": "integer",
                    "description": "起始列（从0开始）"
                },
                "end_col": {
                    "type": "integer",
                    "description": "结束列（包含）"
                }
            },
            "required": ["file_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """读取Excel指定范围的单元格数据"""
        try:
            file_id = params.get("file_id", "")
            sheet_name = params.get("sheet_name")
            start_row = params.get("start_row", 0)
            end_row = params.get("end_row")
            start_col = params.get("start_col", 0)
            end_col = params.get("end_col")

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if doc.file_type != "xlsx":
                    return ToolResult(success=False, error=f"不支持的文件类型: {doc.file_type}，仅支持xlsx")

                if not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 使用openpyxl读取Excel
                try:
                    from openpyxl import load_workbook
                    wb = load_workbook(doc.file_path, read_only=True, data_only=True)

                    # 获取工作表
                    if sheet_name:
                        if sheet_name not in wb.sheetnames:
                            return ToolResult(
                                success=False,
                                error=f"工作表不存在: {sheet_name}，可用工作表: {wb.sheetnames}"
                            )
                        ws = wb[sheet_name]
                    else:
                        ws = wb.active

                    # 确定范围
                    if end_row is None:
                        end_row = ws.max_row - 1  # openpyxl从1开始，我们从0开始
                    if end_col is None:
                        end_col = ws.max_column - 1

                    # 读取数据
                    data = []
                    for row_idx in range(start_row, end_row + 1):
                        row_data = []
                        for col_idx in range(start_col, end_col + 1):
                            cell = ws.cell(row=row_idx + 1, column=col_idx + 1)  # openpyxl从1开始
                            row_data.append(cell.value)
                        data.append(row_data)

                    wb.close()

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "sheet_name": ws.title,
                            "range": {
                                "start_row": start_row,
                                "end_row": end_row,
                                "start_col": start_col,
                                "end_col": end_col
                            },
                            "data": data,
                            "rows": len(data),
                            "cols": len(data[0]) if data else 0
                        }
                    )

                except ImportError:
                    return ToolResult(success=False, error="openpyxl未安装，无法读取Excel文件")
                except Exception as e:
                    return ToolResult(success=False, error=f"读取Excel失败: {str(e)}")

        except Exception as e:
            return ToolResult(success=False, error=f"读取单元格范围失败: {str(e)}")


class ReadSelectionTool(BaseTool):
    """读取用户在编辑器中选中的内容"""

    @property
    def name(self) -> str:
        return "read_selection"

    @property
    def description(self) -> str:
        return """读取用户在编辑器中选中的内容。

使用场景：
- 当用户选中了文档中的部分内容并希望对其进行操作时
- 当需要获取用户当前选中的文本时

注意事项：
- 此工具不需要file_id参数，它从RunContext.active_selection中自动获取选区信息
- 如果用户没有选中任何内容，将返回错误"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_READ

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID（可选，用于验证选区所属文档）"
                }
            },
            "required": []
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """读取用户选中的内容"""
        try:
            # 从上下文获取选区信息
            if not hasattr(context, 'active_selection') or not context.active_selection:
                return ToolResult(
                    success=False,
                    error="用户没有选中任何内容，请先在编辑器中选中文本"
                )

            selection = context.active_selection

            return ToolResult(
                success=True,
                data={
                    "text": selection.get("text", ""),
                    "start_offset": selection.get("start_offset"),
                    "end_offset": selection.get("end_offset"),
                    "paragraph_index": selection.get("paragraph_index"),
                    "file_id": selection.get("file_id")
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=f"读取选区失败: {str(e)}")


class GetDocumentInfoTool(BaseTool):
    """获取文档元数据"""

    @property
    def name(self) -> str:
        return "get_document_info"

    @property
    def description(self) -> str:
        return """获取文档的元数据信息，包括文件名、大小、类型、页数、字数等。

使用场景：
- 当需要了解文档的基本信息时
- 当需要判断文档类型和大小时
- 当需要获取文档的创建时间等元数据时

注意事项：
- 此工具只返回元数据，不返回文档内容
- 如需读取内容，请使用read_document"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_READ

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def cacheable(self) -> bool:
        return True

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                }
            },
            "required": ["file_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """获取文档元数据"""
        try:
            file_id = params.get("file_id", "")

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                # 获取文件统计信息
                file_stats = {}
                if doc.file_path and os.path.exists(doc.file_path):
                    stat = os.stat(doc.file_path)
                    file_stats = {
                        "file_size_bytes": stat.st_size,
                        "created_at": stat.st_ctime,
                        "modified_at": stat.st_mtime
                    }

                    # 尝试获取更详细的统计信息
                    ext = os.path.splitext(doc.file_path)[1].lower()
                    if ext == '.docx':
                        try:
                            from docx import Document as DocxDocument
                            d = DocxDocument(doc.file_path)
                            file_stats["paragraph_count"] = len(d.paragraphs)
                            file_stats["table_count"] = len(d.tables)
                            # 估算字数
                            total_text = " ".join([p.text for p in d.paragraphs])
                            file_stats["word_count"] = len(total_text)
                        except:
                            pass
                    elif ext == '.xlsx':
                        try:
                            from openpyxl import load_workbook
                            wb = load_workbook(doc.file_path, read_only=True)
                            file_stats["sheet_count"] = len(wb.sheetnames)
                            file_stats["sheet_names"] = wb.sheetnames
                            # 统计总行数和列数
                            total_rows = 0
                            total_cols = 0
                            for ws in wb.worksheets:
                                total_rows += ws.max_row
                                total_cols = max(total_cols, ws.max_column)
                            file_stats["total_rows"] = total_rows
                            file_stats["total_cols"] = total_cols
                            wb.close()
                        except:
                            pass

                return ToolResult(
                    success=True,
                    data={
                        "file_id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        "doc_category": doc.doc_category,
                        "status": doc.status,
                        "is_shared": doc.is_shared,
                        "user_id": str(doc.user_id) if doc.user_id else None,
                        "created_at": doc.created_at.isoformat() if doc.created_at else None,
                        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                        **file_stats
                    }
                )

        except Exception as e:
            return ToolResult(success=False, error=f"获取文档信息失败: {str(e)}")


class SearchInDocumentTool(BaseTool):
    """在文档中搜索文本"""

    @property
    def name(self) -> str:
        return "search_in_document"

    @property
    def description(self) -> str:
        return """在指定文档中搜索文本，返回匹配位置和上下文。

使用场景：
- 当需要在文档中查找特定内容时
- 当需要定位某个关键词在文档中的位置时
- 当需要了解某个术语在文档中的使用情况时

注意事项：
- 搜索结果包含匹配位置的上下文
- 支持大小写敏感/不敏感搜索
- 对于大文档，搜索可能需要一些时间"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_READ

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 10000  # 10秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否区分大小写"
                },
                "context_chars": {
                    "type": "integer",
                    "default": 100,
                    "description": "上下文字符数"
                },
                "max_results": {
                    "type": "integer",
                    "default": 20,
                    "description": "最大返回结果数"
                }
            },
            "required": ["file_id", "query"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """在文档中搜索文本"""
        try:
            file_id = params.get("file_id", "")
            query = params.get("query", "")
            case_sensitive = params.get("case_sensitive", False)
            context_chars = params.get("context_chars", 100)
            max_results = params.get("max_results", 20)

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")
            if not query:
                return ToolResult(success=False, error="搜索关键词不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if not doc.file_path or not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 读取文档内容
                ext = os.path.splitext(doc.file_path)[1].lower()
                content = ""

                if ext in ['.txt', '.md']:
                    with open(doc.file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                elif ext == '.docx':
                    try:
                        from docx import Document as DocxDocument
                        d = DocxDocument(doc.file_path)
                        content = "\n".join([p.text for p in d.paragraphs])
                    except Exception as e:
                        return ToolResult(success=False, error=f"读取docx失败: {str(e)}")
                else:
                    return ToolResult(success=False, error=f"不支持的文件格式: {ext}")

                # 执行搜索
                if not case_sensitive:
                    content_lower = content.lower()
                    query_lower = query.lower()
                    matches = []
                    start = 0
                    while len(matches) < max_results:
                        idx = content_lower.find(query_lower, start)
                        if idx == -1:
                            break
                        # 获取上下文
                        ctx_start = max(0, idx - context_chars)
                        ctx_end = min(len(content), idx + len(query) + context_chars)
                        context_text = content[ctx_start:ctx_end]
                        matches.append({
                            "position": idx,
                            "context": context_text,
                            "line_number": content[:idx].count('\n') + 1
                        })
                        start = idx + 1
                else:
                    matches = []
                    start = 0
                    while len(matches) < max_results:
                        idx = content.find(query, start)
                        if idx == -1:
                            break
                        ctx_start = max(0, idx - context_chars)
                        ctx_end = min(len(content), idx + len(query) + context_chars)
                        context_text = content[ctx_start:ctx_end]
                        matches.append({
                            "position": idx,
                            "context": context_text,
                            "line_number": content[:idx].count('\n') + 1
                        })
                        start = idx + 1

                return ToolResult(
                    success=True,
                    data={
                        "file_id": file_id,
                        "query": query,
                        "total_matches": len(matches),
                        "matches": matches,
                        "case_sensitive": case_sensitive
                    }
                )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索失败: {str(e)}")
