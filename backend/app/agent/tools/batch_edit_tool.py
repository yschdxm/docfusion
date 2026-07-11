"""
批量编辑工具 - 一次性执行多个编辑操作

功能：
- 批量执行多个编辑操作
- 支持原子操作（全部成功或全部回滚）
- 支持多种操作类型
"""

import os
import shutil
import logging
from typing import Any, Dict, List
from uuid import uuid4

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select

logger = logging.getLogger(__name__)


class BatchEditTool(BaseTool):
    """批量编辑工具

    一次性执行多个编辑操作，支持原子操作模式。
    """

    @property
    def name(self) -> str:
        return "batch_edit"

    @property
    def description(self) -> str:
        return """一次性执行多个编辑操作，支持原子操作（全部成功或全部回滚）。

使用场景：
- 当需要对文档进行多处修改时
- 当需要保证多个操作要么全部成功，要么全部失败时
- 当需要批量处理文档内容时

支持的操作类型：
- replace_text: 替换文本
- insert_content: 插入内容
- delete_content: 删除内容
- set_style: 设置样式

注意事项：
- 原子模式下，如果任何操作失败，所有更改将被回滚
- 操作按顺序执行，后面的操作可以依赖前面操作的结果
- 建议先使用非原子模式测试，确认无误后再使用原子模式"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_EDIT

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 60000  # 60秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["replace_text", "insert_content", "delete_content", "set_style"],
                                "description": "操作类型"
                            },
                            "params": {
                                "type": "object",
                                "description": "操作参数"
                            }
                        },
                        "required": ["type", "params"]
                    },
                    "description": "操作列表"
                },
                "atomic": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否原子操作（全部成功或全部回滚）"
                }
            },
            "required": ["file_id", "operations"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行批量编辑操作"""
        try:
            file_id = params.get("file_id", "")
            operations = params.get("operations", [])
            atomic = params.get("atomic", True)

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if not operations:
                return ToolResult(success=False, error="操作列表不能为空")

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

                # 检查文件类型
                if doc.file_type not in ['docx', 'txt', 'md']:
                    return ToolResult(
                        success=False,
                        error=f"不支持的文件类型: {doc.file_type}，仅支持docx、txt、md"
                    )

                # 执行操作
                if atomic:
                    return await self._execute_atomic(doc, operations, context)
                else:
                    return await self._execute_sequential(doc, operations, context)

        except Exception as e:
            logger.exception(f"批量编辑失败: {e}")
            return ToolResult(success=False, error=f"批量编辑失败: {str(e)}")

    async def _execute_atomic(
        self,
        doc: Document,
        operations: List[Dict[str, Any]],
        context: ToolContext
    ) -> ToolResult:
        """原子执行：复制文件，在副本上执行所有操作，成功后替换原文件"""
        try:
            # 复制文件到临时位置
            temp_dir = os.path.join(os.path.dirname(doc.file_path), "temp")
            os.makedirs(temp_dir, exist_ok=True)
            temp_file = os.path.join(temp_dir, f"batch_{uuid4().hex[:8]}_{os.path.basename(doc.file_path)}")
            shutil.copy2(doc.file_path, temp_file)

            # 在临时文件上执行所有操作
            executed_ops = []
            try:
                for i, op in enumerate(operations):
                    op_type = op.get("type")
                    op_params = op.get("params", {})

                    # 执行单个操作
                    success = await self._execute_single_op(temp_file, doc.file_type, op_type, op_params)
                    executed_ops.append({
                        "index": i,
                        "type": op_type,
                        "success": success
                    })

                    if not success:
                        raise Exception(f"操作 {i} ({op_type}) 执行失败")

                # 所有操作成功，复制结果到输出目录
                output_dir = os.path.join(os.path.dirname(doc.file_path), "outputs")
                os.makedirs(output_dir, exist_ok=True)
                output_filename = f"batch_{uuid4().hex[:8]}_{doc.original_filename}"
                output_path = os.path.join(output_dir, output_filename)
                shutil.copy2(temp_file, output_path)

                # 注册输出文件
                from app.agent.tools.document_edit_tools import _register_output_file
                output_info = await _register_output_file(output_path, doc.file_type, context.user_id)

                return ToolResult(
                    success=True,
                    data={
                        "message": f"成功执行 {len(operations)} 个操作",
                        "operations_count": len(operations),
                        "executed_operations": executed_ops,
                        **output_info
                    }
                )

            except Exception as e:
                # 操作失败，清理临时文件
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                raise e

            finally:
                # 清理临时目录
                if os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass

        except Exception as e:
            logger.exception(f"原子执行失败: {e}")
            return ToolResult(success=False, error=f"原子执行失败: {str(e)}")

    async def _execute_sequential(
        self,
        doc: Document,
        operations: List[Dict[str, Any]],
        context: ToolContext
    ) -> ToolResult:
        """顺序执行：依次执行每个操作，失败时继续执行后续操作"""
        try:
            executed_ops = []
            current_file = doc.file_path

            for i, op in enumerate(operations):
                op_type = op.get("type")
                op_params = op.get("params", {})

                try:
                    success = await self._execute_single_op(current_file, doc.file_type, op_type, op_params)
                    executed_ops.append({
                        "index": i,
                        "type": op_type,
                        "success": success
                    })
                except Exception as e:
                    executed_ops.append({
                        "index": i,
                        "type": op_type,
                        "success": False,
                        "error": str(e)
                    })

            # 计算成功和失败的数量
            success_count = sum(1 for op in executed_ops if op.get("success"))
            fail_count = len(executed_ops) - success_count

            return ToolResult(
                success=success_count > 0,
                data={
                    "message": f"执行完成: {success_count} 成功, {fail_count} 失败",
                    "operations_count": len(operations),
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "executed_operations": executed_ops
                }
            )

        except Exception as e:
            logger.exception(f"顺序执行失败: {e}")
            return ToolResult(success=False, error=f"顺序执行失败: {str(e)}")

    async def _execute_single_op(
        self,
        file_path: str,
        file_type: str,
        op_type: str,
        op_params: Dict[str, Any]
    ) -> bool:
        """执行单个操作"""
        try:
            if file_type == "docx":
                return await self._execute_docx_op(file_path, op_type, op_params)
            elif file_type in ["txt", "md"]:
                return await self._execute_text_op(file_path, op_type, op_params)
            else:
                raise Exception(f"不支持的文件类型: {file_type}")
        except Exception as e:
            logger.error(f"执行操作失败: {op_type} - {e}")
            raise

    async def _execute_docx_op(
        self,
        file_path: str,
        op_type: str,
        op_params: Dict[str, Any]
    ) -> bool:
        """执行docx文件操作"""
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)

            if op_type == "replace_text":
                old_text = op_params.get("old_text", "")
                new_text = op_params.get("new_text", "")
                if not old_text:
                    raise Exception("old_text不能为空")

                replaced = False
                for paragraph in doc.paragraphs:
                    if old_text in paragraph.text:
                        paragraph.text = paragraph.text.replace(old_text, new_text)
                        replaced = True

                if replaced:
                    doc.save(file_path)
                return replaced

            elif op_type == "insert_content":
                content = op_params.get("content", "")
                position = op_params.get("position", "end")  # "start", "end", "after_paragraph"
                paragraph_index = op_params.get("paragraph_index")

                if position == "start":
                    doc.paragraphs[0].insert_paragraph_before(content)
                elif position == "end":
                    doc.add_paragraph(content)
                elif position == "after_paragraph" and paragraph_index is not None:
                    if 0 <= paragraph_index < len(doc.paragraphs):
                        doc.paragraphs[paragraph_index].insert_paragraph_after(content)
                    else:
                        raise Exception(f"段落索引超出范围: {paragraph_index}")

                doc.save(file_path)
                return True

            elif op_type == "delete_content":
                target = op_params.get("target")
                paragraph_index = op_params.get("paragraph_index")

                if target == "paragraph" and paragraph_index is not None:
                    if 0 <= paragraph_index < len(doc.paragraphs):
                        p = doc.paragraphs[paragraph_index]
                        p.clear()
                        doc.save(file_path)
                        return True
                    else:
                        raise Exception(f"段落索引超出范围: {paragraph_index}")

                return False

            else:
                raise Exception(f"不支持的操作类型: {op_type}")

        except Exception as e:
            logger.error(f"docx操作失败: {op_type} - {e}")
            raise

    async def _execute_text_op(
        self,
        file_path: str,
        op_type: str,
        op_params: Dict[str, Any]
    ) -> bool:
        """执行文本文件操作"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if op_type == "replace_text":
                old_text = op_params.get("old_text", "")
                new_text = op_params.get("new_text", "")
                if not old_text:
                    raise Exception("old_text不能为空")

                if old_text in content:
                    content = content.replace(old_text, new_text)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    return True
                return False

            elif op_type == "insert_content":
                insert_content = op_params.get("content", "")
                position = op_params.get("position", "end")

                if position == "start":
                    content = insert_content + "\n" + content
                elif position == "end":
                    content = content + "\n" + insert_content

                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True

            elif op_type == "delete_content":
                target = op_params.get("target")
                if target == "text_range":
                    start_text = op_params.get("start_text", "")
                    end_text = op_params.get("end_text", "")
                    if start_text and end_text:
                        start_idx = content.find(start_text)
                        end_idx = content.find(end_text, start_idx + len(start_text))
                        if start_idx != -1 and end_idx != -1:
                            content = content[:start_idx] + content[end_idx + len(end_text):]
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            return True
                return False

            else:
                raise Exception(f"不支持的操作类型: {op_type}")

        except Exception as e:
            logger.error(f"文本操作失败: {op_type} - {e}")
            raise
