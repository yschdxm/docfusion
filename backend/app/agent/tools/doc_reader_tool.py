"""
文档阅读工具 - 让LLM能够阅读文档内容

功能：
- 获取文档基本信息
- 读取文档全文或指定部分（支持 offset 区间读取）
- docx 同时输出正文段落和表格内容（按文档顺序，带索引标记）
- xlsx 支持按 sheet + 范围读取单元格
- 支持各种文档类型(docx, xlsx, md, txt等)
"""

from typing import Any, Dict, Optional
import os

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select


class DocReaderTool(BaseTool):
    """文档阅读工具

    让LLM能够阅读文档的内容，了解文档结构和信息。
    支持全文阅读、字符区间阅读、xlsx 单元格范围阅读。
    """

    MAX_CONTENT_LENGTH = 10000  # 单次最大返回内容长度

    @property
    def name(self) -> str:
        return "read_document"

    @property
    def description(self) -> str:
        return """阅读文档的内容，支持全文阅读、字符区间阅读和Excel范围读取。

使用场景：
- 当需要了解文档的具体内容时（这是了解文档内容的首选工具）
- 当RAG检索返回的片段不够完整时
- 当需要查看文档结构时（编辑定位请用 get_document_outline 获取带索引大纲）

阅读模式：
- full: 返回完整内容（受max_length限制）
- head: 返回开头部分（默认）
- tail: 返回结尾部分
- range: 返回指定字符区间（配合 offset 参数），用于阅读长文档的中段

docx 文档说明：
- 输出按文档顺序同时包含正文段落和表格内容（表格以 [表格N] 标记，逐行列出单元格）
- 如需段落/表格/单元格的精确索引，请使用 get_document_outline

xlsx 文档说明：
- 必须配合 sheet_name 参数（可选，默认第一个sheet）
- 用 cell_range 参数指定范围（如 "A1:H50"），不指定则返回前50行
- 返回每个单元格的坐标和值，以及合并单元格信息

注意事项：
- 单次返回内容有长度上限，长文档请用 range 模式分多次读取
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
                    "enum": ["full", "head", "tail", "range"],
                    "default": "head",
                    "description": "阅读模式: full(全文)、head(开头)、tail(结尾)、range(指定区间，需配合offset)"
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "字符偏移量，仅 read_mode=range 时生效，从该字符位置开始读取"
                },
                "max_length": {
                    "type": "integer",
                    "default": 5000,
                    "description": "最大返回字符数，默认5000"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "（仅xlsx）工作表名称，默认第一个工作表"
                },
                "cell_range": {
                    "type": "string",
                    "description": "（仅xlsx）单元格范围，如 \"A1:H50\"，不指定默认前50行"
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
            offset = max(0, int(params.get("offset", 0) or 0))
            sheet_name = params.get("sheet_name")
            cell_range = params.get("cell_range")

            uuid_error = BaseTool.validate_uuid(doc_id, "doc_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

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

                # xlsx 走专门的单元格读取路径
                if doc.file_type == "xlsx":
                    return self._read_xlsx(doc, sheet_name, cell_range, max_length)

                # 其他格式按文本读取
                content, total_length = self._read_doc_content(
                    doc.file_path, read_mode, max_length, offset
                )

                return ToolResult(
                    success=True,
                    data={
                        "doc_id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        "file_size": doc.file_size,
                        "read_mode": read_mode,
                        "offset": offset if read_mode == "range" else None,
                        "total_length": total_length,
                        "content": content,
                        "truncated": (len(content) < total_length) if total_length is not None else (len(content) >= max_length)
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

    def _apply_window(
        self, content: str, read_mode: str, max_length: int, offset: int
    ) -> str:
        """按阅读模式截取内容窗口"""
        if read_mode == "head":
            return content[:max_length]
        elif read_mode == "tail":
            return content[-max_length:] if len(content) > max_length else content
        elif read_mode == "range":
            return content[offset:offset + max_length]
        else:  # full
            return content[:max_length]

    def _read_doc_content(
        self,
        file_path: str,
        read_mode: str,
        max_length: int,
        offset: int
    ) -> tuple:
        """读取文档内容，返回 (内容窗口, 完整内容总长度)"""
        try:
            if not os.path.exists(file_path):
                return f"[文件不存在: {file_path}]", None

            ext = os.path.splitext(file_path)[1].lower()

            if ext in ['.txt', '.md']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return self._apply_window(content, read_mode, max_length, offset), len(content)

            elif ext == '.docx':
                try:
                    from docx import Document as DocxDocument
                    doc = DocxDocument(file_path)
                    # 按文档顺序输出段落和表格，保证表格内容可见
                    content = self._extract_docx_full_content(doc)
                    return self._apply_window(content, read_mode, max_length, offset), len(content)
                except Exception as e:
                    return f"[无法读取docx文件: {str(e)}]", None

            else:
                return f"[暂不支持的文件格式: {ext}，请使用rag_search进行内容检索]", None

        except Exception as e:
            return f"[读取失败: {str(e)}]", None

    def _extract_docx_full_content(self, doc) -> str:
        """按文档顺序提取 docx 的全部内容：段落 + 表格（带索引标记）"""
        parts = []
        para_by_elem = {p._element: p for p in doc.paragraphs}
        table_by_elem = {t._element: t for t in doc.tables}

        table_idx = 0
        for element in doc.element.body:
            if element in para_by_elem:
                text = para_by_elem[element].text
                if text.strip():
                    parts.append(text)
            elif element in table_by_elem:
                table = table_by_elem[element]
                parts.append(f"[表格{table_idx}] ({len(table.rows)}行)")
                for r_idx, row in enumerate(table.rows):
                    cells = [cell.text.strip() for cell in row.cells]
                    parts.append(f"  行{r_idx}: " + " | ".join(cells))
                table_idx += 1

        return "\n".join(parts)

    def _read_xlsx(
        self,
        doc,
        sheet_name: Optional[str],
        cell_range: Optional[str],
        max_length: int
    ) -> ToolResult:
        """读取 xlsx 指定 sheet 的指定范围单元格"""
        from openpyxl import load_workbook
        from openpyxl.utils import range_boundaries, get_column_letter

        try:
            wb = load_workbook(doc.file_path, read_only=True, data_only=True)

            # 选择工作表
            if sheet_name:
                if sheet_name not in wb.sheetnames:
                    available = list(wb.sheetnames)
                    wb.close()
                    return ToolResult(
                        success=False,
                        error=f"工作表不存在: {sheet_name}，可用工作表: {available}"
                    )
                ws = wb[sheet_name]
            else:
                ws = wb[wb.sheetnames[0]]

            # 解析范围
            if cell_range:
                try:
                    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
                except Exception:
                    wb.close()
                    return ToolResult(
                        success=False,
                        error=f"单元格范围格式不正确: {cell_range}，示例: A1:H50"
                    )
            else:
                min_col, min_row = 1, 1
                max_col = ws.max_column or 1
                max_row = min(ws.max_row or 1, 50)

            # 限制单次读取规模
            max_rows_per_read = 200
            if max_row - min_row + 1 > max_rows_per_read:
                max_row = min_row + max_rows_per_read - 1

            # 合并单元格信息
            merged_ranges = []
            try:
                merged_ranges = [str(r) for r in ws.merged_cells.ranges]
            except Exception:
                pass

            # 逐行输出单元格（含坐标）
            lines = []
            lines.append(f"工作表: {ws.title} (总行数≈{ws.max_row}, 总列数≈{ws.max_column})")
            if merged_ranges:
                lines.append(f"合并单元格: {', '.join(merged_ranges)}")
            lines.append(f"读取范围: {get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}")
            lines.append("")

            truncated = False
            current_length = sum(len(line) for line in lines)

            for r_offset, row in enumerate(
                ws.iter_rows(
                    min_row=min_row, max_row=max_row,
                    min_col=min_col, max_col=max_col
                )
            ):
                row_cells = []
                for c_offset, cell in enumerate(row):
                    # read_only 模式下空单元格是 EmptyCell，缺少坐标属性，按枚举位置计算
                    coordinate = f"{get_column_letter(min_col + c_offset)}{min_row + r_offset}"
                    value = cell.value
                    text = "" if value is None else str(value)
                    row_cells.append(f"{coordinate}={text}")
                line = " | ".join(row_cells)
                if current_length + len(line) > max_length:
                    truncated = True
                    break
                lines.append(line)
                current_length += len(line)

            # 在 close 前取好属性
            actual_sheet_name = ws.title
            all_sheets = list(wb.sheetnames)
            wb.close()

            return ToolResult(
                success=True,
                data={
                    "doc_id": str(doc.id),
                    "filename": doc.original_filename,
                    "file_type": "xlsx",
                    "sheet_name": actual_sheet_name,
                    "all_sheets": all_sheets,
                    "range": f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}",
                    "merged_ranges": merged_ranges,
                    "content": "\n".join(lines),
                    "truncated": truncated
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"读取Excel失败: {str(e)}"
            )
