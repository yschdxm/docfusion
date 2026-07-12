"""
获取表格结构工具 - 获取Excel/Word模板的结构信息

功能：
- 获取表格的表头信息
- 获取列名和数据类型
- 获取示例数据
"""

from typing import Any, Dict

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select
from openpyxl import load_workbook
from docx import Document as DocxDocument


class GetTableStructureTool(BaseTool):
    """获取表格结构工具

    分析Excel或Word模板文档，获取表格结构信息。
    这是填表前的必要步骤，用于了解表格的列名和格式。
    """

    @property
    def name(self) -> str:
        return "get_table_structure"

    @property
    def description(self) -> str:
        return """获取表格模板的结构信息(表头、列名、数据类型等)。

使用场景：
- 填表前了解表格结构
- 确定需要提取哪些字段
- 了解表格的格式要求

支持格式：
- Excel (.xlsx): 分析所有工作表
- Word (.docx): 分析文档中的表格

返回信息：
- 表头列表
- 列数
- 示例行数
- 数据类型推断
- **context.preceding_text**（Word文档）：表格前的段落文本，用于理解表格用途

多表格文档注意：
- Word文档中有多个表格时，每个表格都有index和context
- 通过context.preceding_text了解表格的上下文信息
- 根据上下文推断表格用途，确定应填入的数据范围"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "模板文档ID（已废弃，请使用 current_doc_id）"
                },
                "current_doc_id": {
                    "type": "string",
                    "description": "当前在OnlyOffice中打开的文档ID（优先使用）"
                }
            },
            "required": []
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行获取表格结构"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # 优先使用 current_doc_id，其次使用 template_id
            # 从 params 或 context.metadata 中获取
            current_doc_id_from_params = params.get("current_doc_id", "")
            current_doc_id_from_context = context.metadata.get("current_doc_id", "") if context.metadata else ""
            template_id = params.get("template_id", "")

            # 调试日志
            logger.info(f"[GetTableStructure] params: {params}")
            logger.info(f"[GetTableStructure] context.metadata: {context.metadata}")
            logger.info(f"[GetTableStructure] current_doc_id from params: {current_doc_id_from_params}")
            logger.info(f"[GetTableStructure] current_doc_id from context: {current_doc_id_from_context}")
            logger.info(f"[GetTableStructure] template_id from params: {template_id}")

            # 确定要使用的文档ID
            doc_id = current_doc_id_from_params or current_doc_id_from_context or template_id

            if not doc_id:
                return ToolResult(
                    success=False,
                    error="必须提供 current_doc_id 或 template_id"
                )

            # UUID格式校验
            uuid_error = BaseTool.validate_uuid(doc_id, "doc_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档
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

                file_path = doc.file_path
                file_type = doc.file_type

                # 根据文件类型解析
                if file_type == "xlsx":
                    structure = await self._parse_xlsx_structure(file_path)
                elif file_type == "docx":
                    structure = await self._parse_docx_structure(file_path)
                else:
                    return ToolResult(
                        success=False,
                        error=f"不支持的文件格式: {file_type}，只支持xlsx和docx"
                    )

                return ToolResult(
                    success=True,
                    data={
                        "doc_id": doc_id,
                        "filename": doc.original_filename,
                        "file_type": file_type,
                        "structure": structure
                    }
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取表格结构失败: {str(e)}"
            )

    async def _parse_xlsx_structure(self, file_path: str) -> Dict[str, Any]:
        """解析Excel文件结构"""
        structure = {
            "sheets": []
        }

        try:
            wb = load_workbook(file_path, read_only=True, data_only=True)

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]

                # 获取表头（第一行）
                headers = []
                first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
                if first_row:
                    headers = [str(cell) if cell else f"Column_{i+1}" for i, cell in enumerate(first_row)]

                # 获取数据行数
                data_rows = list(sheet.iter_rows(min_row=2, values_only=True))
                row_count = len(data_rows)

                # 获取示例数据（前3行）
                sample_data = []
                for row in data_rows[:3]:
                    row_data = {}
                    for i, (header, cell) in enumerate(zip(headers, row)):
                        row_data[header] = str(cell) if cell is not None else ""
                    if any(row_data.values()):
                        sample_data.append(row_data)

                sheet_info = {
                    "name": sheet_name,
                    "headers": headers,
                    "column_count": len(headers),
                    "row_count": row_count,
                    "sample_data": sample_data
                }
                structure["sheets"].append(sheet_info)

            wb.close()

        except Exception as e:
            structure["error"] = str(e)

        return structure

    async def _parse_docx_structure(self, file_path: str) -> Dict[str, Any]:
        """解析Word文件中的表格结构"""
        structure = {
            "tables": []
        }

        try:
            doc = DocxDocument(file_path)

            # 构建表格位置映射：通过表格在文档中的位置找到其上下文
            table_contexts = self._extract_table_contexts(doc)

            for table_idx, table in enumerate(doc.tables):
                # 获取表头（第一行）
                headers = []
                if table.rows:
                    first_row = table.rows[0]
                    headers = [cell.text.strip() if cell.text.strip() else f"Column_{i+1}"
                              for i, cell in enumerate(first_row.cells)]

                # 获取数据行数
                row_count = len(table.rows) - 1 if len(table.rows) > 1 else 0

                # 获取示例数据（前3行）
                sample_data = []
                for row in table.rows[1:4]:  # 跳过表头，取3行
                    row_data = {}
                    for i, (header, cell) in enumerate(zip(headers, row.cells)):
                        row_data[header] = cell.text.strip()
                    if any(row_data.values()):
                        sample_data.append(row_data)

                # 获取表格上下文（如标题）
                context = table_contexts.get(table_idx, {})

                table_info = {
                    "index": table_idx,
                    "headers": headers,
                    "column_count": len(headers),
                    "row_count": row_count,
                    "sample_data": sample_data,
                    "context": context
                }
                structure["tables"].append(table_info)

        except Exception as e:
            structure["error"] = str(e)

        return structure

    def _extract_table_contexts(self, doc: DocxDocument) -> Dict[int, Dict[str, Any]]:
        """提取每个表格的上下文信息（前面的段落文本）"""
        contexts = {}
        table_idx = 0
        prev_paragraphs = []

        for element in doc.element.body:
            if element.tag.endswith('tbl'):  # 表格元素
                # 收集表格前的段落文本（最多5段）
                context_text = []
                for p in prev_paragraphs[-5:]:
                    text = p.text.strip()
                    if text:
                        context_text.append(text)

                contexts[table_idx] = {
                    "preceding_text": context_text
                }

                table_idx += 1
                prev_paragraphs = []
            elif element.tag.endswith('p'):  # 段落元素
                for p in doc.paragraphs:
                    if p._element is element:
                        prev_paragraphs.append(p)
                        break

        return contexts
