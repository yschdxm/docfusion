"""
文件读取工具 - 读取文档内容

功能：
- 读取 Word、TXT、MD 文件的内容
- 读取 Excel 文件（限制1000行以内）
- 支持指定读取范围
"""

import logging
import os
from typing import Any, Dict

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select

logger = logging.getLogger(__name__)


class FileReaderTool(BaseTool):
    """文件读取工具

    读取文档内容，支持 Word、TXT、MD 文件，以及 Excel 文件（限制1000行以内）。
    """

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return """读取文档文件的内容。

支持的文件类型：
- Word (.docx)：读取段落文本
- 文本 (.txt, .md)：读取全文内容
- Excel (.xlsx)：读取表格数据（限制1000行以内）

使用场景：
- 需要查看文档的具体内容
- 从非结构化文档中提取信息
- 查看 Excel 表格数据

注意事项：
- Excel 文件超过1000行会被拒绝
- 返回的内容可能被截断，建议使用 read_mode 控制读取范围"""

    @property
    def timeout_ms(self) -> int:
        return 30000  # 30秒

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
                    "description": "读取模式: full(全文)、head(开头)、tail(结尾)、range(指定范围)"
                },
                "max_rows": {
                    "type": "integer",
                    "default": 100,
                    "description": "Excel 最大读取行数，默认100行，最大1000行"
                },
                "start_row": {
                    "type": "integer",
                    "default": 1,
                    "description": "Excel 起始行号（range模式使用）"
                },
                "end_row": {
                    "type": "integer",
                    "default": 100,
                    "description": "Excel 结束行号（range模式使用）"
                }
            },
            "required": ["doc_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行文件读取"""
        try:
            doc_id = params.get("doc_id", "")
            read_mode = params.get("read_mode", "head")
            max_rows = min(params.get("max_rows", 100), 1000)  # 最大1000行
            start_row = params.get("start_row", 1)
            end_row = params.get("end_row", 100)

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

                # 检查文件类型
                file_type = doc.file_type.lower() if doc.file_type else ""
                if file_type not in ["docx", "txt", "md", "xlsx"]:
                    return ToolResult(
                        success=False,
                        error=f"不支持的文件类型: {file_type}，仅支持 docx、txt、md、xlsx"
                    )

                # 读取文件内容
                if file_type == "xlsx":
                    content = await self._read_excel(
                        doc.file_path, read_mode, max_rows, start_row, end_row
                    )
                else:
                    content = await self._read_text_file(doc.file_path, file_type)

                return ToolResult(
                    success=True,
                    data={
                        "doc_id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": file_type,
                        "content": content,
                        "read_mode": read_mode,
                    }
                )

        except Exception as e:
            logger.exception(f"[FileReaderTool] 读取失败: {e}")
            return ToolResult(
                success=False,
                error=f"文件读取失败: {str(e)}"
            )

    async def _read_text_file(self, file_path: str, file_type: str) -> str:
        """读取文本文件（txt、md、docx）"""
        try:
            if not os.path.exists(file_path):
                return f"[文件不存在: {file_path}]"

            if file_type in ["txt", "md"]:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return content[:50000]  # 限制50000字符

            elif file_type == "docx":
                from docx import Document as DocxDocument
                doc = DocxDocument(file_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                content = "\n".join(paragraphs)
                return content[:50000]  # 限制50000字符

            else:
                return f"[不支持的文件类型: {file_type}]"

        except Exception as e:
            return f"[读取失败: {str(e)}]"

    async def _read_excel(
        self,
        file_path: str,
        read_mode: str,
        max_rows: int,
        start_row: int,
        end_row: int
    ) -> str:
        """读取 Excel 文件"""
        try:
            if not os.path.exists(file_path):
                return f"[文件不存在: {file_path}]"

            from openpyxl import load_workbook

            wb = load_workbook(file_path, read_only=True, data_only=True)
            ws = wb.active

            # 获取总行数
            total_rows = ws.max_row
            if total_rows > 1000:
                wb.close()
                return f"[Excel文件行数({total_rows})超过1000行限制，建议使用 query_pg_database 查询结构化数据]"

            # 确定读取范围
            if read_mode == "head":
                rows_to_read = min(max_rows, total_rows)
                start = 1
                end = rows_to_read
            elif read_mode == "tail":
                rows_to_read = min(max_rows, total_rows)
                start = max(1, total_rows - rows_to_read + 1)
                end = total_rows
            elif read_mode == "range":
                start = max(1, start_row)
                end = min(end_row, total_rows)
            else:  # full
                start = 1
                end = min(total_rows, 1000)  # 最大1000行

            # 读取数据
            rows = []
            for row_idx, row in enumerate(ws.iter_rows(min_row=start, max_row=end, values_only=True), start=start):
                row_data = [str(cell) if cell is not None else "" for cell in row]
                rows.append("\t".join(row_data))

            wb.close()

            # 格式化输出
            header = f"[Excel文件: {os.path.basename(file_path)}]\n"
            header += f"[总行数: {total_rows}, 读取范围: {start}-{end}]\n\n"
            content = header + "\n".join(rows)

            return content[:50000]  # 限制50000字符

        except Exception as e:
            return f"[读取Excel失败: {str(e)}]"
