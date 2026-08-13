"""
文档结构大纲工具 - 返回带索引的文档结构视图

功能：
- docx: 返回带索引的段落列表([P0]...)和表格列表([T0] 含单元格索引)
- md/txt: 返回带行号的内容视图
- xlsx: 返回 sheet 清单、维度、合并单元格信息

索引约定（全局统一，重要）：
- 段落索引 [Pn] 与编辑工具(edit_paragraph等)的 paragraph_index
  完全一致：docx 只数【非空段落】，从0开始
- 表格索引 [Tn] 从0开始，按文档中出现顺序
- 单元格索引用 [TnRmCk] 表示第n个表格第m行第k列，均从0开始
- md/txt 的行号 [Ln] 是【所有行】的行号（含空行），从0开始，
  与编辑工具的 paragraph_index 一致
"""

import os
from typing import Any, Dict, List

from sqlalchemy import select

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document


class GetDocumentOutlineTool(BaseTool):
    """获取文档结构大纲

    编辑文档前必须先调用本工具获取索引，
    禁止凭猜测使用 paragraph_index / table_index。
    """

    MAX_CELL_PREVIEW = 30      # 单元格预览最大字符数
    MAX_PARA_PREVIEW = 80      # 段落预览最大字符数
    MAX_ITEMS = 500            # 单次返回的最大条目数

    @property
    def name(self) -> str:
        return "get_document_outline"

    @property
    def description(self) -> str:
        return """获取文档的结构大纲（带索引），用于编辑前的定位。

使用场景：
- 编辑文档前必须先调用本工具，获取段落索引[Pn]、表格索引[Tn]、单元格索引[TnRmCk]
- 禁止凭猜测使用 paragraph_index / table_index，必须用本工具返回的索引

索引约定：
- [Pn]: 第n个非空段落（从0开始），与 edit_paragraph 等编辑工具的 paragraph_index 完全一致
- [Tn]: 第n个表格（从0开始，按文档中出现顺序）
- [TnRmCk]: 第n个表格第m行第k列的单元格（均从0开始）
- md/txt: [Ln] 为行号（含空行，从0开始），与编辑工具的 paragraph_index 一致

返回内容：
- docx: 按文档顺序列出段落（含样式名和文本预览）和表格（含行列数和单元格索引）
- md/txt: 带行号的内容列表
- xlsx: sheet清单、每个sheet的维度、合并单元格区域、前几行预览

参数说明：
- offset/limit: 条目较多时分页读取（条目指段落/表格/行/sheet）"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "起始条目偏移（分页用），默认0"
                },
                "limit": {
                    "type": "integer",
                    "default": 200,
                    "description": "最大返回条目数，默认200"
                },
                "include_table_cells": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否包含表格单元格内容预览，默认true"
                }
            },
            "required": ["doc_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            doc_id = params.get("doc_id", "")
            uuid_error = BaseTool.validate_uuid(doc_id, "doc_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            offset = max(0, int(params.get("offset", 0) or 0))
            limit = min(max(1, int(params.get("limit", 200) or 200)), self.MAX_ITEMS)
            include_cells = params.get("include_table_cells", True)

            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == doc_id)
                )
                doc = result.scalar_one_or_none()

            if not doc:
                return ToolResult(success=False, error=f"文档不存在: {doc_id}")

            if not os.path.exists(doc.file_path):
                return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

            file_type = doc.file_type
            if file_type == "docx":
                outline = self._outline_docx(doc.file_path, offset, limit, include_cells)
            elif file_type in ("md", "txt"):
                outline = self._outline_text(doc.file_path, offset, limit)
            elif file_type == "xlsx":
                outline = self._outline_xlsx(doc.file_path, include_cells)
            else:
                return ToolResult(
                    success=False,
                    error=f"不支持的文件格式: {file_type}"
                )

            return ToolResult(
                success=True,
                data={
                    "doc_id": doc_id,
                    "filename": doc.original_filename,
                    "file_type": file_type,
                    **outline
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=f"获取文档大纲失败: {str(e)}")

    # ──────────────────────────── docx ────────────────────────────

    def _outline_docx(
        self, file_path: str, offset: int, limit: int, include_cells: bool
    ) -> Dict[str, Any]:
        from docx import Document as DocxDocument

        doc = DocxDocument(file_path)

        # 建立 element → paragraph/table 的映射，按文档顺序遍历
        para_by_elem = {p._element: p for p in doc.paragraphs}
        table_by_elem = {t._element: t for t in doc.tables}

        items: List[Dict[str, Any]] = []
        para_edit_idx = 0   # 非空段落索引（与编辑工具一致）
        table_idx = 0
        total_paragraphs = 0
        total_tables = 0

        for element in doc.element.body:
            if element in para_by_elem:
                total_paragraphs += 1
                p = para_by_elem[element]
                text = p.text.strip()
                if not text:
                    continue  # 空段落不占索引，与编辑工具保持一致
                style_name = p.style.name if p.style else "Normal"
                preview = text[:self.MAX_PARA_PREVIEW]
                if len(text) > self.MAX_PARA_PREVIEW:
                    preview += "…"
                items.append({
                    "type": "paragraph",
                    "index": para_edit_idx,
                    "label": f"[P{para_edit_idx}]",
                    "style": style_name,
                    "preview": preview,
                    "char_count": len(text),
                })
                para_edit_idx += 1
            elif element in table_by_elem:
                total_tables += 1
                t = table_by_elem[element]
                row_count = len(t.rows)
                col_count = len(t.columns) if row_count else 0
                table_item: Dict[str, Any] = {
                    "type": "table",
                    "index": table_idx,
                    "label": f"[T{table_idx}]",
                    "row_count": row_count,
                    "col_count": col_count,
                }
                if include_cells:
                    rows_preview = []
                    for r_idx, row in enumerate(t.rows):
                        cells = []
                        for c_idx, cell in enumerate(row.cells):
                            cell_text = cell.text.strip()
                            preview = cell_text[:self.MAX_CELL_PREVIEW]
                            if len(cell_text) > self.MAX_CELL_PREVIEW:
                                preview += "…"
                            cells.append(f"[T{table_idx}R{r_idx}C{c_idx}]{preview if preview else '(空)'}")
                        rows_preview.append(" | ".join(cells))
                    table_item["rows"] = rows_preview
                items.append(table_item)
                table_idx += 1

        sliced = items[offset:offset + limit]

        return {
            "total_paragraphs": total_paragraphs,
            "editable_paragraph_count": para_edit_idx,
            "table_count": total_tables,
            "total_items": len(items),
            "offset": offset,
            "has_more": offset + limit < len(items),
            "items": sliced,
        }

    # ──────────────────────────── md / txt ────────────────────────────

    def _outline_text(self, file_path: str, offset: int, limit: int) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]

        items = []
        for idx, line in enumerate(lines):
            preview = line[:self.MAX_PARA_PREVIEW]
            if len(line) > self.MAX_PARA_PREVIEW:
                preview += "…"
            items.append({
                "type": "line",
                "index": idx,
                "label": f"[L{idx}]",
                "preview": preview if preview else "(空行)",
            })

        sliced = items[offset:offset + limit]

        return {
            "total_lines": len(lines),
            "total_items": len(items),
            "offset": offset,
            "has_more": offset + limit < len(items),
            "items": sliced,
            "note": "行号[Ln]（含空行）与编辑工具的 paragraph_index 一致",
        }

    # ──────────────────────────── xlsx ────────────────────────────

    def _outline_xlsx(self, file_path: str, include_cells: bool) -> Dict[str, Any]:
        from openpyxl import load_workbook

        wb = load_workbook(file_path, read_only=True, data_only=True)
        sheets_info = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_info: Dict[str, Any] = {
                "name": sheet_name,
                "max_row": ws.max_row,
                "max_col": ws.max_column,
            }

            # 合并单元格区域（read_only 模式下可用）
            try:
                merged = [str(r) for r in ws.merged_cells.ranges]
                if merged:
                    sheet_info["merged_ranges"] = merged
            except Exception:
                pass

            if include_cells:
                # 前5行预览
                preview_rows = []
                for r_idx, row in enumerate(
                    ws.iter_rows(min_row=1, max_row=min(5, ws.max_row or 1), values_only=True),
                    start=1,
                ):
                    cells = []
                    for value in row:
                        text = "" if value is None else str(value)
                        preview = text[:self.MAX_CELL_PREVIEW]
                        if len(text) > self.MAX_CELL_PREVIEW:
                            preview += "…"
                        cells.append(preview if preview else "(空)")
                    preview_rows.append({
                        "row": r_idx,
                        "cells": cells,
                    })
                sheet_info["preview_rows"] = preview_rows
                sheet_info["note"] = "完整单元格内容请用 read_document 按 sheet+range 读取"

            sheets_info.append(sheet_info)

        wb.close()

        return {
            "sheet_count": len(sheets_info),
            "sheets": sheets_info,
        }
