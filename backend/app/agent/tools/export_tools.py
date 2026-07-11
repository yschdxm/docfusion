"""
导出工具 - 文档导出和预览

功能：
- 将文档导出为指定格式
- 生成文档预览
"""

import os
import logging
from typing import Any, Dict

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select

logger = logging.getLogger(__name__)


class ExportDocumentTool(BaseTool):
    """导出文档工具"""

    @property
    def name(self) -> str:
        return "export_document"

    @property
    def description(self) -> str:
        return """将文档导出为指定格式并生成下载链接。

使用场景：
- 当需要将文档转换为其他格式时
- 当需要生成PDF版本时
- 当需要导出为HTML网页时

支持的导出格式：
- pdf: PDF文档
- docx: Word文档
- xlsx: Excel文档
- md: Markdown文档
- txt: 纯文本文档
- html: HTML网页

注意事项：
- 导出可能需要一些时间，特别是转换为PDF时
- 某些格式转换可能会丢失部分格式信息"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_CONVERT

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
                "format": {
                    "type": "string",
                    "enum": ["pdf", "docx", "xlsx", "md", "txt", "html"],
                    "description": "导出格式"
                },
                "options": {
                    "type": "object",
                    "description": "导出选项（可选）"
                }
            },
            "required": ["file_id", "format"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """导出文档"""
        try:
            file_id = params.get("file_id", "")
            export_format = params.get("format", "")
            options = params.get("options", {})

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if not export_format:
                return ToolResult(success=False, error="导出格式不能为空")

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

                # 执行导出
                try:
                    output_dir = os.path.join(os.path.dirname(doc.file_path), "outputs")
                    os.makedirs(output_dir, exist_ok=True)

                    output_filename = f"{os.path.splitext(doc.original_filename)[0]}.{export_format}"
                    output_path = os.path.join(output_dir, output_filename)

                    # 根据源格式和目标格式选择转换方法
                    success = await self._convert_file(
                        doc.file_path,
                        doc.file_type,
                        output_path,
                        export_format,
                        options
                    )

                    if success:
                        # 注册输出文件
                        from app.agent.tools.document_edit_tools import _register_output_file
                        output_info = await _register_output_file(output_path, export_format, context.user_id)

                        return ToolResult(
                            success=True,
                            data={
                                "message": f"文档已导出为 {export_format} 格式",
                                "source_format": doc.file_type,
                                "target_format": export_format,
                                **output_info
                            }
                        )
                    else:
                        return ToolResult(success=False, error=f"导出失败: 不支持从 {doc.file_type} 转换为 {export_format}")

                except Exception as e:
                    logger.exception(f"导出文档失败: {e}")
                    return ToolResult(success=False, error=f"导出文档失败: {str(e)}")

        except Exception as e:
            logger.exception(f"导出文档失败: {e}")
            return ToolResult(success=False, error=f"导出文档失败: {str(e)}")

    async def _convert_file(
        self,
        source_path: str,
        source_format: str,
        output_path: str,
        target_format: str,
        options: Dict[str, Any]
    ) -> bool:
        """执行文件转换"""
        try:
            # 如果源格式和目标格式相同，直接复制
            if source_format == target_format:
                import shutil
                shutil.copy2(source_path, output_path)
                return True

            # 文本格式转换
            if source_format in ['txt', 'md'] and target_format in ['txt', 'md']:
                with open(source_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True

            # docx转换
            if source_format == 'docx':
                if target_format == 'txt':
                    from docx import Document as DocxDocument
                    doc = DocxDocument(source_path)
                    content = "\n".join([p.text for p in doc.paragraphs])
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    return True

                elif target_format == 'md':
                    from docx import Document as DocxDocument
                    doc = DocxDocument(source_path)
                    # 简单的docx到md转换
                    md_content = ""
                    for para in doc.paragraphs:
                        if para.style.name.startswith('Heading'):
                            level = int(para.style.name[-1])
                            md_content += "#" * level + " " + para.text + "\n\n"
                        else:
                            md_content += para.text + "\n\n"
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(md_content)
                    return True

            # xlsx转换
            if source_format == 'xlsx':
                if target_format == 'csv':
                    import pandas as pd
                    df = pd.read_excel(source_path)
                    df.to_csv(output_path, index=False, encoding='utf-8-sig')
                    return True

                elif target_format == 'txt':
                    import pandas as pd
                    df = pd.read_excel(source_path)
                    df.to_string(output_path, index=False)
                    return True

            # PDF转换需要额外的库支持
            if target_format == 'pdf':
                # 这里需要集成PDF转换库（如reportlab、weasyprint等）
                # 暂时返回False
                logger.warning(f"PDF转换暂不支持: {source_format} -> {target_format}")
                return False

            # HTML转换
            if target_format == 'html':
                if source_format in ['txt', 'md']:
                    with open(source_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{os.path.basename(source_path)}</title>
</head>
<body>
    <pre>{content}</pre>
</body>
</html>"""
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    return True

            logger.warning(f"不支持的转换: {source_format} -> {target_format}")
            return False

        except Exception as e:
            logger.exception(f"文件转换失败: {e}")
            return False


class GeneratePreviewTool(BaseTool):
    """生成预览工具"""

    @property
    def name(self) -> str:
        return "generate_preview"

    @property
    def description(self) -> str:
        return """生成文档的预览图或预览页面。

使用场景：
- 当需要快速预览文档内容时
- 当需要生成文档缩略图时
- 当需要查看文档的HTML预览时

预览类型：
- text: 文本预览（默认）
- html: HTML预览
- thumbnail: 缩略图预览

注意事项：
- thumbnail类型需要额外的库支持
- 预览内容会被截断到max_length"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DOCUMENT_CONVERT

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 30000  # 30秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "preview_type": {
                    "type": "string",
                    "enum": ["text", "html", "thumbnail"],
                    "default": "text",
                    "description": "预览类型"
                },
                "max_length": {
                    "type": "integer",
                    "default": 5000,
                    "description": "最大预览长度"
                }
            },
            "required": ["file_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """生成预览"""
        try:
            file_id = params.get("file_id", "")
            preview_type = params.get("preview_type", "text")
            max_length = params.get("max_length", 5000)

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

                if not doc.file_path or not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 生成预览
                try:
                    if preview_type == "text":
                        preview_content = await self._generate_text_preview(doc.file_path, doc.file_type, max_length)
                    elif preview_type == "html":
                        preview_content = await self._generate_html_preview(doc.file_path, doc.file_type, max_length)
                    elif preview_type == "thumbnail":
                        preview_content = await self._generate_thumbnail_preview(doc.file_path, doc.file_type)
                    else:
                        return ToolResult(success=False, error=f"不支持的预览类型: {preview_type}")

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "preview_type": preview_type,
                            "preview_content": preview_content,
                            "truncated": len(str(preview_content)) >= max_length
                        }
                    )

                except Exception as e:
                    logger.exception(f"生成预览失败: {e}")
                    return ToolResult(success=False, error=f"生成预览失败: {str(e)}")

        except Exception as e:
            logger.exception(f"生成预览失败: {e}")
            return ToolResult(success=False, error=f"生成预览失败: {str(e)}")

    async def _generate_text_preview(self, file_path: str, file_type: str, max_length: int) -> str:
        """生成文本预览"""
        try:
            if file_type in ['txt', 'md']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return content[:max_length]

            elif file_type == 'docx':
                from docx import Document as DocxDocument
                doc = DocxDocument(file_path)
                content = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                return content[:max_length]

            elif file_type == 'xlsx':
                import pandas as pd
                df = pd.read_excel(file_path, nrows=10)
                return df.to_string(index=False)[:max_length]

            else:
                return f"[不支持的文件格式: {file_type}]"

        except Exception as e:
            return f"[预览生成失败: {str(e)}]"

    async def _generate_html_preview(self, file_path: str, file_type: str, max_length: int) -> str:
        """生成HTML预览"""
        try:
            text_content = await self._generate_text_preview(file_path, file_type, max_length)

            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>文档预览</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; }}
    </style>
</head>
<body>
    <pre>{text_content}</pre>
</body>
</html>"""
            return html_content

        except Exception as e:
            return f"<p>预览生成失败: {str(e)}</p>"

    async def _generate_thumbnail_preview(self, file_path: str, file_type: str) -> str:
        """生成缩略图预览"""
        # 缩略图生成需要额外的库支持（如Pillow、pdf2image等）
        # 暂时返回文本预览
        return await self._generate_text_preview(file_path, file_type, 500)
