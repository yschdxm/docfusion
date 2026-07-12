"""
文档编辑工具集

将每个编辑操作封装为独立的BaseTool。
采用"复制原始文件 → 在副本上原地修改 → 保存"的方式，保留原始排版格式。
支持：文本替换、段落重写、段落插入、标题调整、列表格式化、段落拆分、样式设置、格式转换。
"""

import csv
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.core.config import get_settings
from app.db.postgres import async_session
from app.models.document import Document
from app.services.document_processor import DocxParser, MdParser, TxtParser, XlsxParser
from app.services.llm_service import llm_service


logger = logging.getLogger(__name__)
settings = get_settings()

CONVERT_RULES = {
    "docx": {"md", "txt"},
    "md": {"docx", "txt"},
    "txt": {"md", "docx"},
    "xlsx": {"csv"},
}


# ──────────────────────────── 公共辅助函数 ────────────────────────────

async def _get_doc_info(file_id: str) -> Optional[Dict[str, Any]]:
    """通过数据库查询文档信息，返回 {file_path, file_type, original_filename, doc_id, is_output}"""
    try:
        doc_uuid = UUID(file_id) if isinstance(file_id, str) else file_id
    except ValueError:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(Document).where(Document.id == doc_uuid)
        )
        doc = result.scalar_one_or_none()
        if doc and doc.file_path and os.path.exists(doc.file_path):
            return {
                "file_path": doc.file_path,
                "file_type": doc.file_type,
                "original_filename": doc.original_filename or os.path.basename(doc.file_path),
                "doc_id": str(doc.id),
                "is_output": (doc.doc_category == "output"),
            }
    return None


def _safe_output_filename(filename: str, default_suffix: str = ".docx") -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (filename or "").strip())
    clean = clean.strip(" ._") or f"generated_{uuid4().hex[:8]}{default_suffix}"
    if "." not in clean:
        clean = f"{clean}{default_suffix}"
    return clean


async def _register_output_file(output_path: str, file_type: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """将输出文件注册到数据库，返回 output_file_id、output_filename 和 download_url"""
    output_filename = os.path.basename(output_path)
    async with async_session() as db:
        output_doc = Document(
            filename=output_filename,
            original_filename=output_filename,
            file_path=output_path,
            file_type=file_type,
            doc_category="output",
            status="completed",
            file_size=os.path.getsize(output_path),
            user_id=user_id,
        )
        db.add(output_doc)
        await db.commit()
        await db.refresh(output_doc)
        return {
            "output_file_id": str(output_doc.id),
            "output_filename": output_filename,
            "download_url": f"/api/v1/documents/{output_doc.id}/download",
        }


async def _update_output_file_size(file_path: str):
    """更新已注册输出文件的大小"""
    async with async_session() as db:
        result = await db.execute(
            select(Document).where(Document.file_path == file_path)
        )
        doc = result.scalar_one_or_none()
        if doc:
            doc.file_size = os.path.getsize(file_path)
            await db.commit()


def _copy_and_open_docx(file_path: str, original_filename: str) -> tuple:
    """复制 docx 文件到 outputs 目录，用 python-docx 打开副本。"""
    from docx import Document as DocxDocument
    from pathlib import Path

    output_dir = Path(settings.UPLOAD_DIR) / "outputs"
    output_dir.mkdir(exist_ok=True)
    output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
    output_path = str(output_dir / output_filename)
    shutil.copy2(file_path, output_path)
    doc = DocxDocument(output_path)
    return doc, output_path


async def _resolve_edit_target(doc_info: Dict[str, Any], output_file_id: Optional[str]) -> tuple:
    """解析编辑目标：首次编辑复制副本，后续编辑在已有输出文件上操作。

    Returns:
        (source_file_path, original_filename, is_new_copy)
        - source_file_path: 应该读取/打开的文件路径
        - original_filename: 用于生成新输出文件名
        - is_new_copy: True=需要注册DB, False=原地修改已有文件
    """
    # 有 output_file_id → 在已有输出文件上操作
    if output_file_id:
        output_info = await _get_doc_info(output_file_id)
        if output_info:
            return output_info["file_path"], doc_info["original_filename"], False

    # 文件本身是输出文件
    if doc_info.get("is_output"):
        return doc_info["file_path"], doc_info["original_filename"], False

    # 首次编辑 → 需要复制
    return doc_info["file_path"], doc_info["original_filename"], True


# ──────────────────────────── 文本处理辅助 ────────────────────────────

def _find_paragraph_by_index(doc, index: int):
    """获取 doc.paragraphs 中第 index 个非空段落。"""
    editable = [p for p in doc.paragraphs if p.text.strip()]
    if 0 <= index < len(editable):
        return editable[index]
    return None


def _get_editable_paragraphs(doc) -> list:
    """获取所有非空段落列表。"""
    return [p for p in doc.paragraphs if p.text.strip()]


def _set_paragraph_text(paragraph, new_text: str):
    """设置段落文本，保留第一个 run 的格式。"""
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = new_text


def _make_change_record(op_name: str, index: int, before: str, after: str, reason: str) -> Dict[str, Any]:
    return {
        "op": op_name,
        "paragraph_index": index,
        "before": before[:300],
        "after": after[:300],
        "reason": reason,
    }


def _strip_heading_prefix(text: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", text).strip()


def _strip_list_prefix(text: str) -> str:
    return re.sub(r"^(?:[-*]|\d+\.)\s+", "", text).strip()


def _split_paragraph(text: str, separator: Optional[str]) -> List[str]:
    if separator:
        parts = [part.strip() for part in text.split(separator) if part.strip()]
        return parts or [text]
    parts = [part.strip() for part in re.split(r"(?<=[。！？；;.!?])", text) if part.strip()]
    return parts or [text]


def _get_parser(file_type: str):
    """获取文档解析器"""
    parsers = {
        "docx": DocxParser(),
        "xlsx": XlsxParser(),
        "md": MdParser(),
        "txt": TxtParser(),
    }
    return parsers.get(file_type)


# ──────────────────────────── 文档编辑工具 ────────────────────────────

def _add_docx_content(doc, content: str) -> None:
    """按常见 Markdown/纯文本结构写入 docx。"""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            doc.add_paragraph()
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            doc.add_heading(heading_match.group(2).strip(), level=min(len(heading_match.group(1)), 6))
            continue
        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        if bullet_match:
            doc.add_paragraph(bullet_match.group(1).strip(), style="List Bullet")
            continue
        number_match = re.match(r"^\d+[.)]\s+(.+)$", line)
        if number_match:
            doc.add_paragraph(number_match.group(1).strip(), style="List Number")
            continue
        doc.add_paragraph(line)


class CreateWordDocumentTool(BaseTool):
    """从零创建 Word 文档工具"""

    @property
    def name(self) -> str:
        return "create_word_document"

    @property
    def description(self) -> str:
        return "未选择模板或没有现成文档时，根据用户提供的标题和正文内容新建一个Word(.docx)文档，并自动保存到文档管理的输出文件中。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "文档标题"},
                "content": {"type": "string", "description": "文档正文，支持简单Markdown标题、列表"},
                "filename": {"type": "string", "description": "输出文件名，可选"},
            },
            "required": ["title", "content"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        from docx import Document as DocxDocument
        from docx.oxml.ns import qn
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        title = str(params.get("title", "")).strip()
        content = str(params.get("content", "")).strip()
        if not title:
            return ToolResult(success=False, error="文档标题不能为空")
        if not content:
            return ToolResult(success=False, error="文档正文不能为空")

        output_dir = Path(settings.UPLOAD_DIR) / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        requested_filename = params.get("filename") or f"{title}.docx"
        output_filename = f"generated_{uuid4().hex[:8]}_{_safe_output_filename(str(requested_filename), '.docx')}"
        if not output_filename.lower().endswith(".docx"):
            output_filename = f"{output_filename}.docx"
        output_path = str(output_dir / output_filename)

        doc = DocxDocument()
        styles = doc.styles
        styles["Normal"].font.name = "宋体"
        styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        styles["Normal"].font.size = Pt(11)
        title_para = doc.add_heading(title, level=0)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_docx_content(doc, content)
        doc.save(output_path)

        reg = await _register_output_file(output_path, "docx", user_id=getattr(context, "user_id", None))
        return ToolResult(success=True, data={"message": "已新建Word文档并保存到文档管理", "output_file": output_path, **reg, "output_format": "docx"})


class ReplaceTextTool(BaseTool):
    """文本替换工具"""

    @property
    def name(self) -> str:
        return "replace_text"

    @property
    def description(self) -> str:
        return "替换文档中的指定文本。需要提供文档ID、目标段落索引、要替换的原文本和新文本。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "old_text": {"type": "string", "description": "要替换的原文本"},
                "new_text": {"type": "string", "description": "替换后的新文本"},
                "reason": {"type": "string", "description": "替换原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "old_text", "new_text"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_info["file_type"]
        paragraph_index = params["paragraph_index"]
        old_text = params["old_text"]
        new_text = params["new_text"]
        output_file_id = params.get("output_file_id")

        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if file_type == "docx":
            if is_new:
                doc, output_path = _copy_and_open_docx(source_path, original_filename)
            else:
                from docx import Document as DocxDocument
                doc = DocxDocument(source_path)
                output_path = source_path

            paragraph = _find_paragraph_by_index(doc, paragraph_index)
            if not paragraph:
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = paragraph.text
            _set_paragraph_text(paragraph, before.replace(old_text, new_text) if old_text else new_text)
            doc.save(output_path)
        else:
            with open(source_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]

            if not (0 <= paragraph_index < len(lines)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = lines[paragraph_index]
            lines[paragraph_index] = before.replace(old_text, new_text) if old_text else new_text

            if is_new:
                from pathlib import Path
                output_dir = Path(settings.UPLOAD_DIR) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
                output_path = str(output_dir / output_filename)
            else:
                output_path = source_path

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        reg = await _finish_edit(output_path, file_type, is_new, context)
        after_text = lines[paragraph_index] if file_type != "docx" else paragraph.text

        return ToolResult(
            success=True,
            data={
                "message": f"已将第 {paragraph_index + 1} 段中的 '{old_text}' 替换为 '{new_text}'",
                "output_file": output_path,
                **reg,
                "changes": [_make_change_record("replace_text", paragraph_index, before, after_text, params.get("reason", ""))],
            },
        )


class RewriteParagraphTool(BaseTool):
    """LLM重写段落工具"""

    @property
    def name(self) -> str:
        return "rewrite_paragraph"

    @property
    def description(self) -> str:
        return "使用LLM重写指定段落。需要提供文档ID、目标段落索引和重写指令。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "rewrite_instruction": {"type": "string", "description": "重写指令"},
                "reason": {"type": "string", "description": "重写原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "rewrite_instruction"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_info["file_type"]
        paragraph_index = params["paragraph_index"]
        rewrite_instruction = params.get("rewrite_instruction", "请重写此段落。")
        output_file_id = params.get("output_file_id")

        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if file_type == "docx":
            if is_new:
                doc, output_path = _copy_and_open_docx(source_path, original_filename)
            else:
                from docx import Document as DocxDocument
                doc = DocxDocument(source_path)
                output_path = source_path

            paragraph = _find_paragraph_by_index(doc, paragraph_index)
            if not paragraph:
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = paragraph.text
            new_text = await llm_service.rewrite_paragraph_text(before, rewrite_instruction)
            _set_paragraph_text(paragraph, new_text)
            doc.save(output_path)
        else:
            with open(source_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]

            if not (0 <= paragraph_index < len(lines)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = lines[paragraph_index]
            new_text = await llm_service.rewrite_paragraph_text(before, rewrite_instruction)
            lines[paragraph_index] = new_text

            if is_new:
                from pathlib import Path
                output_dir = Path(settings.UPLOAD_DIR) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
                output_path = str(output_dir / output_filename)
            else:
                output_path = source_path

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        reg = await _finish_edit(output_path, file_type, is_new, context)

        return ToolResult(
            success=True,
            data={
                "message": f"已重写第 {paragraph_index + 1} 段",
                "output_file": output_path,
                **reg,
                "changes": [_make_change_record("rewrite_paragraph", paragraph_index, before, new_text, params.get("reason", ""))],
            },
        )


class InsertAfterTool(BaseTool):
    """段落后插入工具"""

    @property
    def name(self) -> str:
        return "insert_after"

    @property
    def description(self) -> str:
        return "在指定段落后插入新内容。需要提供文档ID、目标段落索引和要插入的文本。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "text": {"type": "string", "description": "要插入的文本"},
                "style": {"type": "string", "description": "段落样式（可选，默认Normal）"},
                "reason": {"type": "string", "description": "插入原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "text"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        insert_text = params.get("text", "").strip()
        if not insert_text:
            return ToolResult(success=False, error="插入文本不能为空")

        file_type = doc_info["file_type"]
        paragraph_index = params["paragraph_index"]
        style = params.get("style", "Normal")
        output_file_id = params.get("output_file_id")

        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if file_type == "docx":
            if is_new:
                doc, output_path = _copy_and_open_docx(source_path, original_filename)
            else:
                from docx import Document as DocxDocument
                doc = DocxDocument(source_path)
                output_path = source_path

            editable = _get_editable_paragraphs(doc)
            if not (0 <= paragraph_index < len(editable)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            target_para = editable[paragraph_index]
            new_para = target_para.insert_paragraph_after(insert_text)
            if style and style != "Normal":
                try:
                    new_para.style = style
                except (KeyError, ValueError):
                    pass
            doc.save(output_path)
        else:
            with open(source_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]

            if not (0 <= paragraph_index < len(lines)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            lines.insert(paragraph_index + 1, insert_text)

            if is_new:
                from pathlib import Path
                output_dir = Path(settings.UPLOAD_DIR) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
                output_path = str(output_dir / output_filename)
            else:
                output_path = source_path

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        reg = await _finish_edit(output_path, file_type, is_new, context)

        return ToolResult(
            success=True,
            data={
                "message": f"已在第 {paragraph_index + 1} 段后插入新内容",
                "output_file": output_path,
                **reg,
                "changes": [_make_change_record("insert_after", paragraph_index + 1, "", insert_text, params.get("reason", ""))],
            },
        )


class HeadingPromoteTool(BaseTool):
    """标题级别调整工具"""

    @property
    def name(self) -> str:
        return "heading_promote"

    @property
    def description(self) -> str:
        return "调整标题级别。需要提供文档ID、目标段落索引和目标级别（1-6）。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "level": {"type": "integer", "description": "目标标题级别（1-6）"},
                "reason": {"type": "string", "description": "调整原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "level"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_info["file_type"]
        paragraph_index = params["paragraph_index"]
        level = max(1, min(6, int(params.get("level", 1))))
        output_file_id = params.get("output_file_id")

        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if file_type == "docx":
            if is_new:
                doc, output_path = _copy_and_open_docx(source_path, original_filename)
            else:
                from docx import Document as DocxDocument
                doc = DocxDocument(source_path)
                output_path = source_path

            paragraph = _find_paragraph_by_index(doc, paragraph_index)
            if not paragraph:
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
            paragraph.style = f"Heading {level}"
            after = f"[{paragraph.style.name}] {paragraph.text}"
            doc.save(output_path)
        else:
            with open(source_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]

            if not (0 <= paragraph_index < len(lines)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = lines[paragraph_index]
            clean = _strip_heading_prefix(before)
            lines[paragraph_index] = f"{'#' * level} {clean}"
            after = lines[paragraph_index]

            if is_new:
                from pathlib import Path
                output_dir = Path(settings.UPLOAD_DIR) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
                output_path = str(output_dir / output_filename)
            else:
                output_path = source_path

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        reg = await _finish_edit(output_path, file_type, is_new, context)

        return ToolResult(
            success=True,
            data={
                "message": f"已将第 {paragraph_index + 1} 段调整为 Heading {level}",
                "output_file": output_path,
                **reg,
                "changes": [_make_change_record("heading_promote", paragraph_index, before, after, params.get("reason", ""))],
            },
        )


class ListFormatTool(BaseTool):
    """列表格式化工具"""

    @property
    def name(self) -> str:
        return "list_format"

    @property
    def description(self) -> str:
        return "将指定段落转换为列表格式。需要提供文档ID、段落索引列表和列表类型（bullet/number）。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_indexes": {"type": "array", "items": {"type": "integer"}, "description": "段落索引列表"},
                "list_type": {"type": "string", "enum": ["bullet", "number"], "description": "列表类型"},
                "reason": {"type": "string", "description": "格式化原因（可选）"},
            },
            "required": ["file_id", "paragraph_indexes", "list_type"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_info["file_type"]
        indexes = params.get("paragraph_indexes", [])
        list_type = params.get("list_type", "bullet")
        output_file_id = params.get("output_file_id")
        changes = []

        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if file_type == "docx":
            if is_new:
                doc, output_path = _copy_and_open_docx(source_path, original_filename)
            else:
                from docx import Document as DocxDocument
                doc = DocxDocument(source_path)
                output_path = source_path

            editable = _get_editable_paragraphs(doc)
            for position, index in enumerate(indexes, start=1):
                if not (0 <= index < len(editable)):
                    continue
                paragraph = editable[index]
                before = paragraph.text
                clean_text = _strip_list_prefix(before)
                if list_type == "number":
                    _set_paragraph_text(paragraph, f"{position}. {clean_text}")
                    try:
                        paragraph.style = "List Number"
                    except (KeyError, ValueError):
                        pass
                else:
                    _set_paragraph_text(paragraph, f"- {clean_text}")
                    try:
                        paragraph.style = "List Bullet"
                    except (KeyError, ValueError):
                        pass
                changes.append(_make_change_record("list_format", index, before, paragraph.text, params.get("reason", "")))
            doc.save(output_path)
        else:
            with open(source_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]

            for position, index in enumerate(indexes, start=1):
                if not (0 <= index < len(lines)):
                    continue
                before = lines[index]
                clean_text = _strip_list_prefix(before)
                if list_type == "number":
                    lines[index] = f"{position}. {clean_text}"
                else:
                    lines[index] = f"- {clean_text}"
                changes.append(_make_change_record("list_format", index, before, lines[index], params.get("reason", "")))

            if is_new:
                from pathlib import Path
                output_dir = Path(settings.UPLOAD_DIR) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
                output_path = str(output_dir / output_filename)
            else:
                output_path = source_path

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        reg = await _finish_edit(output_path, file_type, is_new, context)

        return ToolResult(
            success=True,
            data={
                "message": f"已将 {len(changes)} 个段落格式化为{'有序' if list_type == 'number' else '无序'}列表",
                "output_file": output_path,
                **reg,
                "changes": changes,
            },
        )


class ParagraphSplitTool(BaseTool):
    """段落拆分工具"""

    @property
    def name(self) -> str:
        return "paragraph_split"

    @property
    def description(self) -> str:
        return "将指定段落拆分为多个段落。需要提供文档ID、目标段落索引和可选的分隔符。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "separator": {"type": "string", "description": "分隔符（可选，默认按句号拆分）"},
                "reason": {"type": "string", "description": "拆分原因（可选）"},
            },
            "required": ["file_id", "paragraph_index"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_info["file_type"]
        paragraph_index = params["paragraph_index"]
        separator = params.get("separator")
        output_file_id = params.get("output_file_id")

        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if file_type == "docx":
            if is_new:
                doc, output_path = _copy_and_open_docx(source_path, original_filename)
            else:
                from docx import Document as DocxDocument
                doc = DocxDocument(source_path)
                output_path = source_path

            editable = _get_editable_paragraphs(doc)
            if not (0 <= paragraph_index < len(editable)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")

            paragraph = editable[paragraph_index]
            before = paragraph.text
            parts = _split_paragraph(before, separator)
            if len(parts) <= 1:
                return ToolResult(success=True, data={"message": "段落无法拆分（未找到分隔点）"})

            style = paragraph.style
            _set_paragraph_text(paragraph, parts[0])
            current_para = paragraph
            for part in parts[1:]:
                new_para = current_para.insert_paragraph_after(part)
                try:
                    new_para.style = style
                except (KeyError, ValueError):
                    pass
                if paragraph.runs:
                    ref_run = paragraph.runs[0]
                    for run in new_para.runs:
                        run.font.name = ref_run.font.name
                        run.font.size = ref_run.font.size
                        run.font.bold = ref_run.font.bold
                        run.font.italic = ref_run.font.italic
                current_para = new_para
            doc.save(output_path)
        else:
            with open(source_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]

            if not (0 <= paragraph_index < len(lines)):
                return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")
            before = lines[paragraph_index]
            parts = _split_paragraph(before, separator)
            if len(parts) <= 1:
                return ToolResult(success=True, data={"message": "段落无法拆分（未找到分隔点）"})
            lines[paragraph_index] = parts[0]
            for offset, part in enumerate(parts[1:], start=1):
                lines.insert(paragraph_index + offset, part)

            if is_new:
                from pathlib import Path
                output_dir = Path(settings.UPLOAD_DIR) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output_filename = f"edited_{uuid4().hex[:8]}_{original_filename}"
                output_path = str(output_dir / output_filename)
            else:
                output_path = source_path

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        reg = await _finish_edit(output_path, file_type, is_new, context)

        return ToolResult(
            success=True,
            data={
                "message": f"已将第 {paragraph_index + 1} 段拆分为 {len(parts)} 个段落",
                "output_file": output_path,
                **reg,
                "changes": [_make_change_record("paragraph_split", paragraph_index, before, "\n".join(parts), params.get("reason", ""))],
            },
        )


class SetTextStyleTool(BaseTool):
    """字体样式设置工具"""

    @property
    def name(self) -> str:
        return "set_text_style"

    @property
    def description(self) -> str:
        return "设置指定段落的字体样式。仅支持docx文件。首次编辑使用原始文档ID，后续编辑使用上一步返回的output_file_id。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID（首次用原始ID，后续用上次返回的output_file_id）"},
                "paragraph_indexes": {"type": "array", "items": {"type": "integer"}, "description": "段落索引列表"},
                "font_name": {"type": "string", "description": "字体名称（可选）"},
                "font_size_pt": {"type": "number", "description": "字体大小（pt，可选）"},
                "reason": {"type": "string", "description": "设置原因（可选）"},
            },
            "required": ["file_id", "paragraph_indexes"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        from docx.shared import Pt

        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")
        if doc_info["file_type"] != "docx":
            return ToolResult(success=False, error="字体样式设置仅支持docx文件")

        output_file_id = params.get("output_file_id")
        source_path, original_filename, is_new = await _resolve_edit_target(doc_info, output_file_id)

        if is_new:
            doc, output_path = _copy_and_open_docx(source_path, original_filename)
        else:
            from docx import Document as DocxDocument
            doc = DocxDocument(source_path)
            output_path = source_path

        editable = _get_editable_paragraphs(doc)
        source_indexes = params.get("paragraph_indexes", [])
        font_name = params.get("font_name", "")
        font_size_pt = params.get("font_size_pt")
        changes = []

        for index in source_indexes:
            if not (0 <= index < len(editable)):
                continue
            paragraph = editable[index]
            before = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
            for run in paragraph.runs:
                if font_name:
                    run.font.name = font_name
                if font_size_pt is not None:
                    run.font.size = Pt(font_size_pt)
            after = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
            changes.append(_make_change_record("set_text_style", index, before, after, params.get("reason", "")))

        doc.save(output_path)
        reg = await _finish_edit(output_path, "docx", is_new, context)

        return ToolResult(
            success=True,
            data={
                "message": f"已设置 {len(changes)} 个段落的字体样式",
                "output_file": output_path,
                **reg,
                "changes": changes,
            },
        )


class ConvertTool(BaseTool):
    """格式转换工具"""

    @property
    def name(self) -> str:
        return "convert"

    @property
    def description(self) -> str:
        return "转换文档格式。支持：docx<->md, docx<->txt, md<->txt, xlsx->csv。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "target_format": {"type": "string", "enum": ["docx", "md", "txt", "csv"], "description": "目标格式"},
                "reason": {"type": "string", "description": "转换原因（可选）"},
            },
            "required": ["file_id", "target_format"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_info = await _get_doc_info(params["file_id"])
        if not doc_info:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_info["file_type"]
        target_format = params.get("target_format", "").lower()

        if target_format not in CONVERT_RULES.get(file_type, set()):
            return ToolResult(success=False, error=f"不支持从 {file_type} 转换为 {target_format}")

        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_info["file_path"])

        from pathlib import Path
        output_dir = Path(settings.UPLOAD_DIR) / "outputs"
        output_dir.mkdir(exist_ok=True)
        base_name = f"edited_{uuid4().hex[:8]}_{doc_info['original_filename']}".rsplit(".", 1)[0]
        output_filename = f"{base_name}.{target_format}"
        output_path = str(output_dir / output_filename)

        if target_format == "docx":
            content = parsed_data.get("full_text", "")
            DocxParser.write(content, output_path, {
                "paragraphs": parsed_data.get("paragraphs", []),
                "tables": parsed_data.get("tables", []),
            })
        elif target_format == "md":
            MdParser.write(parsed_data.get("full_text", ""), output_path)
        elif target_format == "txt":
            TxtParser.write(parsed_data.get("full_text", ""), output_path)
        elif target_format == "csv":
            rows = []
            sheets = parsed_data.get("sheets", [])
            if sheets:
                rows = sheets[0].get("data", [])
            with open(output_path, "w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file)
                for row in rows:
                    writer.writerow(row)

        reg = await _register_output_file(output_path, target_format, user_id=getattr(context, "user_id", None))

        return ToolResult(
            success=True,
            data={
                "message": f"已将文档从 {file_type} 转换为 {target_format}",
                "output_file": output_path,
                **reg,
                "output_format": target_format,
            },
        )


# ──────────────────────────── 工具共用的完成处理 ────────────────────────────

async def _finish_edit(output_path: str, file_type: str, is_new_copy: bool, context) -> Dict[str, str]:
    """编辑完成后处理：注册DB或更新大小。"""
    if is_new_copy:
        return await _register_output_file(output_path, file_type, user_id=getattr(context, "user_id", None))
    else:
        await _update_output_file_size(output_path)
        # 通过文件路径查找已有的 output_file_id
        output_file_id = await _get_file_id_by_path(output_path)
        return {
            "output_file_id": output_file_id,
            "output_filename": os.path.basename(output_path),
            "download_url": f"/api/v1/documents/{output_file_id}/download",
        }


async def _get_file_id_by_path(file_path: str) -> str:
    """通过文件路径查询数据库中的文档ID"""
    async with async_session() as db:
        result = await db.execute(
            select(Document.id).where(Document.file_path == file_path)
        )
        doc_id = result.scalar_one_or_none()
        return str(doc_id) if doc_id else ""
