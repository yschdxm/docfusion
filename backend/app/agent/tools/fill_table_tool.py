"""
表格填写工具 - 使用数据填写表格模板

功能：
- 将数据填写到Excel模板
- 将数据填写到Word模板
- 支持追加或覆盖模式
"""

from typing import Any, Dict, List
import os
import shutil
import uuid
from pathlib import Path

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select
from app.core.config import get_settings

# 获取settings
settings = get_settings()


class FillTableTool(BaseTool):
    """表格填写工具

    使用提供的数据填写表格模板，支持Excel和Word格式。
    这是填表流程的最后一步。
    """

    @property
    def name(self) -> str:
        return "fill_table"

    @property
    def description(self) -> str:
        return """使用提供的数据填写表格模板。支持增量填表和多表格文档。

使用场景：
- 首次填写表格（基于模板创建新文件）
- 增量追加数据到已生成的输出文件
- 将提取的数据填入模板（支持多表格Word文档）

支持格式：
- Excel (.xlsx)
- Word (.docx)

填写模式：
- overwrite: 覆盖现有内容（保留表头），首次填写使用
- append: 追加到现有内容后面，增量填表使用

多表格文档填写（重要）：
- Word文档中有多个表格时，**必须**使用 target_table_index 指定填写哪个表格
- 表格索引从0开始，按文档中出现的顺序
- **关键**：多表格文档中，每个表格通常有特定用途，需按用途过滤数据
  - 先通过 get_table_structure 了解每个表格的用途和当前状态（是否为空/有占位行）
  - 根据用途筛选数据，不要将所有数据填入每个表格

fill_mode 详解（针对指定表格的操作）：
- **overwrite**: 清空【target_table_index 指定的表格】，然后填入新数据
  - 用于：表格为空、只有表头、有占位空行、或需要替换旧数据
  - 效果：该表格的所有现有数据行被删除，只保留表头，然后填入新数据

- **append**: 在【target_table_index 指定的表格】现有内容后面添加新行
  - 用于：该表格已有有效数据，需要继续添加更多数据时
  - 效果：新行添加到该表格的末尾，原有数据保留

重要概念：fill_mode 是针对单个表格的操作，不是文档级别的操作。
- 填写表格2时，即使表格1已经填好，也不要用 append 来"跳到"表格2
- 填写每个表格时，根据该表格当前是否为空/有占位行来选择 fill_mode

多表格填写流程：
1. 获取表格结构，分析每个表格的用途和当前状态（row_count 是否大于1，sample_data 是否为空）
2. 查询所需数据
3. 填写表格0：
   - fill_mode="overwrite"（因为表格通常只有表头或空行）
   - target_table_index=0
   - 这会创建新文件
4. 填写表格1：
   - 检查表格1状态：如果只有表头/空行 → 用 overwrite；如果已有有效数据 → 用 append
   - output_doc_id=上一步返回的ID（必须提供，表示继续填写同一个文件）
   - target_table_index=1（指定填写第二个表格）
5. 后续表格同理，每个独立判断 fill_mode

注意：
- 数据格式必须是数组，每个元素是一行的数据
- 字段名必须与表头匹配
- 首次填写后output_file_id会返回在结果中，后续追加需要传入output_doc_id
- 本工具只会填写文档中已有的表格，不会创建新表格
- **多表格文档必须指定target_table_index，否则数据会填错位**"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "模板文档ID（首次填写时必需，增量追加时也需要提供）"
                },
                "output_doc_id": {
                    "type": "string",
                    "description": "已生成的输出文档ID（增量追加时提供，首次填写不传）"
                },
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "description": "一行数据，字段名对应表头"
                    },
                    "description": "填表数据，数组形式，每个元素是一行的数据"
                },
                "fill_mode": {
                    "type": "string",
                    "enum": ["append", "overwrite"],
                    "default": "overwrite",
                    "description": """填写模式:
- overwrite: 覆盖现有内容（保留表头），首次填写使用
- append: 追加到现有内容后面，增量填表使用"""
                },
                "target_table_index": {
                    "type": "integer",
                    "description": "目标表格索引（从0开始），用于多表格文档。如果不指定，自动选择第一个合适的表格"
                }
            },
            "required": ["data"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行表格填写"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            template_id = params.get("template_id", "")
            output_doc_id = params.get("output_doc_id", "")
            data = params.get("data", [])
            fill_mode = params.get("fill_mode", "overwrite")
            target_table_index = params.get("target_table_index")

            if not data:
                return ToolResult(
                    success=False,
                    error="填表数据不能为空"
                )

            # 判断是新建文件还是操作已有文件
            # 只要有 output_doc_id，就是操作已有文件（不管 fill_mode 是 overwrite 还是 append）
            is_update_existing = bool(output_doc_id)

            if not is_update_existing and not template_id:
                return ToolResult(
                    success=False,
                    error="首次填写必须提供template_id"
                )

            async with async_session() as db:
                if is_update_existing:
                    # 操作已有输出文件（可能是覆盖某个表格，也可能是追加）
                    return await self._update_existing_file(
                        db, output_doc_id, template_id, data, fill_mode, target_table_index, logger
                    )
                else:
                    # 首次填写，基于模板创建新文件
                    return await self._create_new_file(
                        db, template_id, data, fill_mode, target_table_index, logger
                    )

        except Exception as e:
            logger.exception(f"表格填写失败: {e}")
            return ToolResult(
                success=False,
                error=f"表格填写失败: {str(e)}"
            )

    async def _create_new_file(
        self, db, template_id: str, data: List[Dict], fill_mode: str, target_table_index: int, logger
    ) -> ToolResult:
        """基于模板创建新输出文件"""
        # 查询模板文档
        result = await db.execute(
            select(Document).where(Document.id == template_id)
        )
        template_doc = result.scalar_one_or_none()

        if not template_doc:
            return ToolResult(
                success=False,
                error=f"模板文档不存在: {template_id}"
            )

        file_path = template_doc.file_path
        file_type = template_doc.file_type

        # 创建输出文件
        upload_dir = Path(settings.UPLOAD_DIR)
        output_dir = upload_dir / "outputs"
        output_dir.mkdir(exist_ok=True)

        output_filename = f"filled_{uuid.uuid4().hex[:8]}_{template_doc.original_filename}"
        output_path = output_dir / output_filename

        # 复制模板到输出位置
        shutil.copy2(file_path, output_path)

        # 根据文件类型填写
        if file_type == "xlsx":
            success = await self._fill_excel(output_path, data, fill_mode)
        elif file_type == "docx":
            success = await self._fill_word(output_path, data, fill_mode, target_table_index)
        else:
            return ToolResult(
                success=False,
                error=f"不支持的文件格式: {file_type}"
            )

        if not success:
            return ToolResult(
                success=False,
                error="表格填写失败"
            )

        # 创建输出文档记录
        output_doc = Document(
            filename=output_filename,
            original_filename=output_filename,
            file_path=str(output_path),
            file_type=file_type,
            doc_category="output",
            status="completed",
            file_size=os.path.getsize(output_path)
        )
        db.add(output_doc)
        await db.commit()
        await db.refresh(output_doc)

        logger.info(f"[FillTableTool] 创建新文件成功: {output_filename}, 填写{len(data)}行")

        return ToolResult(
            success=True,
            data={
                "filled_rows": len(data),
                "total_rows": len(data),
                "output_file_id": str(output_doc.id),
                "output_filename": output_filename,
                "download_url": f"/api/v1/documents/{output_doc.id}/download"
            },
            metadata={
                "template_id": template_id,
                "fill_mode": fill_mode,
                "is_new_file": True
            }
        )

    async def _update_existing_file(
        self, db, output_doc_id: str, template_id: str, data: List[Dict], fill_mode: str, target_table_index: int, logger
    ) -> ToolResult:
        """更新已有输出文件（覆盖或追加指定表格）"""
        # 查询输出文档
        result = await db.execute(
            select(Document).where(Document.id == output_doc_id)
        )
        output_doc = result.scalar_one_or_none()

        if not output_doc:
            return ToolResult(
                success=False,
                error=f"输出文档不存在: {output_doc_id}"
            )

        file_path = Path(output_doc.file_path)
        file_type = output_doc.file_type

        if not file_path.exists():
            return ToolResult(
                success=False,
                error=f"输出文件不存在: {file_path}"
            )

        # 根据 fill_mode 更新数据
        if file_type == "xlsx":
            success = await self._fill_excel(file_path, data, fill_mode)
        elif file_type == "docx":
            success = await self._fill_word(file_path, data, fill_mode, target_table_index)
        else:
            return ToolResult(
                success=False,
                error=f"不支持的文件格式: {file_type}"
            )

        if not success:
            return ToolResult(
                success=False,
                error="表格更新失败"
            )

        # 更新文件大小
        output_doc.file_size = os.path.getsize(file_path)
        await db.commit()

        logger.info(f"[FillTableTool] 更新文件成功: {fill_mode}模式，{len(data)}行到 {output_doc.filename}")

        return ToolResult(
            success=True,
            data={
                "filled_rows": len(data),
                "output_file_id": str(output_doc.id),
                "output_filename": output_doc.original_filename,
                "download_url": f"/api/v1/documents/{output_doc.id}/download"
            },
            metadata={
                "output_doc_id": output_doc_id,
                "template_id": template_id,
                "fill_mode": fill_mode,
                "is_update_existing": True
            }
        )

    async def _fill_excel(self, file_path: str, data: List[Dict], fill_mode: str) -> bool:
        """填写Excel文件"""
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path)
            ws = wb.active

            # 获取表头
            headers = []
            first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if first_row:
                headers = [str(cell) if cell else f"Column_{i+1}" for i, cell in enumerate(first_row)]

            # 处理填写模式
            if fill_mode == "overwrite":
                # 清空数据行，保留表头
                # 删除现有数据行
                for row in range(ws.max_row, 1, -1):
                    ws.delete_rows(row)

            # 填写数据
            for row_data in data:
                row_values = []
                for header in headers:
                    value = row_data.get(header, "")
                    row_values.append(value)
                ws.append(row_values)

            wb.save(file_path)
            wb.close()

            return True

        except Exception as e:
            print(f"填写Excel失败: {e}")
            return False

    async def _fill_word(self, file_path: str, data: List[Dict], fill_mode: str, target_table_index: int = None) -> bool:
        """填写Word文件 - 支持多表格智能填写"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            from docx import Document

            logger.info(f"[FillTableTool] 开始填写Word文件: {file_path}, 数据行数: {len(data)}")

            doc = Document(file_path)

            if not doc.tables:
                logger.error("[FillTableTool] 文档中没有表格")
                return False

            logger.info(f"[FillTableTool] 文档中共有 {len(doc.tables)} 个表格")

            # 获取第一个表格的表头作为参考
            first_table = doc.tables[0]
            headers = []
            if first_table.rows:
                first_row = first_table.rows[0]
                headers = [cell.text.strip() if cell.text.strip() else f"Column_{i+1}"
                          for i, cell in enumerate(first_row.cells)]
                logger.info(f"[FillTableTool] 表头: {headers}")

            # 根据fill_mode处理
            if fill_mode == "overwrite":
                # 确定目标表格
                target_table = None
                if target_table_index is not None and target_table_index < len(doc.tables):
                    # 使用指定的表格索引
                    target_table = doc.tables[target_table_index]
                    logger.info(f"[FillTableTool] 使用指定的表格 {target_table_index} 作为填写目标")
                else:
                    # 找到第一个非空表格（已有数据或只有表头）进行覆盖
                    for i, table in enumerate(doc.tables):
                        logger.info(f"[FillTableTool] 检查表格 {i}: {len(table.rows)} 行")
                        if len(table.rows) >= 1:  # 至少要有表头
                            target_table = table
                            logger.info(f"[FillTableTool] 选择表格 {i} 作为填写目标")
                            break

                if not target_table:
                    logger.error("[FillTableTool] 没有找到有效的表格")
                    return False

                # 删除现有数据行，保留表头
                rows_to_remove = len(target_table.rows) - 1
                while len(target_table.rows) > 1:
                    target_table._tbl.remove(target_table.rows[-1]._tr)
                logger.info(f"[FillTableTool] 删除旧数据行: {rows_to_remove} 行")

                # 填写数据到目标表格
                filled_count = 0
                for row_data in data:
                    row = target_table.add_row()
                    for i, header in enumerate(headers):
                        if i < len(row.cells):
                            value = row_data.get(header, "")
                            if value is None:
                                value = ""
                            row.cells[i].text = str(value)
                    filled_count += 1

                logger.info(f"[FillTableTool] 填写完成, 新增 {filled_count} 行到表格")

            else:  # append模式
                # 确定目标表格
                target_table = None
                if target_table_index is not None and target_table_index < len(doc.tables):
                    # 使用指定的表格索引
                    target_table = doc.tables[target_table_index]
                    logger.info(f"[FillTableTool] 使用指定的表格 {target_table_index} 作为追加目标")
                else:
                    # 找到第一个可以追加的表格
                    for i, table in enumerate(doc.tables):
                        logger.info(f"[FillTableTool] 检查表格 {i}: {len(table.rows)} 行")
                        if len(table.rows) >= 1:
                            target_table = table
                            logger.info(f"[FillTableTool] 选择表格 {i} 作为追加目标")
                            break

                if not target_table:
                    logger.error("[FillTableTool] 没有找到有效的表格进行追加")
                    return False

                # 追加数据
                filled_count = 0
                for row_data in data:
                    row = target_table.add_row()
                    for i, header in enumerate(headers):
                        if i < len(row.cells):
                            value = row_data.get(header, "")
                            if value is None:
                                value = ""
                            row.cells[i].text = str(value)
                    filled_count += 1

                logger.info(f"[FillTableTool] 追加完成, 新增 {filled_count} 行到表格")

            doc.save(file_path)
            logger.info(f"[FillTableTool] 文档已保存: {file_path}")

            return True

        except Exception as e:
            logger.exception(f"[FillTableTool] 填写Word失败: {e}")
            return False
