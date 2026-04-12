"""
文档编辑工具集

从dev-op分支的document_agent.py迁移而来，将每个编辑操作封装为独立的BaseTool。
支持：文本替换、段落重写、段落插入、标题调整、列表格式化、段落拆分、样式设置、格式转换。
"""

import csv
import logging
import os
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.core.config import get_settings
from app.services.document_processor import DocxParser, MdParser, TxtParser, XlsxParser
from app.services.llm_service import llm_service


logger = logging.getLogger(__name__)
settings = get_settings()


HEADING_STYLE_KEYWORDS = ("heading", "标题", "title", "subtitle")
FONT_NAME_KEYWORDS = (
    "宋体",
    "黑体",
    "仿宋",
    "楷体",
    "微软雅黑",
    "times new roman",
    "arial",
)
FONT_SIZE_ALIASES = {
    "初号": 42.0,
    "小初": 36.0,
    "一号": 26.0,
    "小一": 24.0,
    "二号": 22.0,
    "小二": 18.0,
    "三号": 16.0,
    "小三": 15.0,
    "四号": 14.0,
    "小四": 12.0,
    "五号": 10.5,
    "小五": 9.0,
    "六号": 7.5,
    "小六": 6.5,
}

CONVERT_RULES = {
    "docx": {"md", "txt"},
    "md": {"docx", "txt"},
    "txt": {"md", "docx"},
    "xlsx": {"csv"},
}


def _get_parser(file_type: str):
    """获取文档解析器"""
    parsers = {
        "docx": DocxParser(),
        "xlsx": XlsxParser(),
        "md": MdParser(),
        "txt": TxtParser(),
    }
    return parsers.get(file_type)


def _is_heading_style(style_name: str) -> bool:
    normalized = (style_name or "").strip().lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in HEADING_STYLE_KEYWORDS)


def _build_editable_structure(parsed_data: Dict[str, Any], file_type: str) -> Dict[str, Any]:
    """构建可编辑的文档结构"""
    paragraphs: List[Dict[str, Any]] = []

    if file_type == "docx":
        docx_paragraphs = parsed_data.get("paragraphs", [])
        body_candidates = []
        for paragraph in docx_paragraphs:
            text = (paragraph.get("text") or "").strip()
            if not text:
                continue
            style_name = paragraph.get("style") or "Normal"
            item = {
                "index": len(body_candidates),
                "text": text,
                "style": style_name,
                "source_paragraph_index": paragraph.get("source_index"),
            }
            if not _is_heading_style(style_name):
                body_candidates.append(item)
        if body_candidates:
            for index, paragraph in enumerate(body_candidates):
                paragraph["index"] = index
                paragraphs.append(paragraph)
        else:
            for paragraph in docx_paragraphs:
                text = (paragraph.get("text") or "").strip()
                if not text:
                    continue
                paragraphs.append(
                    {
                        "index": len(paragraphs),
                        "text": text,
                        "style": paragraph.get("style") or "Normal",
                        "source_paragraph_index": paragraph.get("source_index"),
                    }
                )
    elif file_type == "md":
        for raw_line in parsed_data.get("full_text", "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            style = "Normal"
            text = line
            heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading_match:
                style = f"Heading {len(heading_match.group(1))}"
                text = heading_match.group(2).strip()
            paragraphs.append({"index": len(paragraphs), "text": text, "style": style})
    elif file_type == "txt":
        for line in parsed_data.get("paragraphs", []):
            text = line.strip()
            if text:
                paragraphs.append({"index": len(paragraphs), "text": text, "style": "Normal"})
    elif file_type == "xlsx":
        for sheet_idx, sheet in enumerate(parsed_data.get("sheets", [])):
            paragraphs.append(
                {
                    "index": len(paragraphs),
                    "text": f"Sheet {sheet.get('name', sheet_idx)} with {sheet.get('rows', 0)} rows and {sheet.get('cols', 0)} cols",
                    "style": "SheetSummary",
                }
            )

    tables = []
    if file_type == "docx":
        for table_index, rows in enumerate(parsed_data.get("tables", [])):
            tables.append({"table_index": table_index, "rows": rows})
    elif file_type == "xlsx":
        for table_index, sheet in enumerate(parsed_data.get("sheets", [])):
            tables.append({"table_index": table_index, "rows": sheet.get("data", [])})

    return {"file_type": file_type, "paragraphs": paragraphs, "tables": tables}


def _generate_output(document: Dict[str, Any], output_format: str, original_data: Dict[str, Any]) -> str:
    """生成输出文件"""
    output_filename = f"output_{uuid4().hex}.{output_format}"
    output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if output_format == "docx":
        DocxParser.write(
            _render_text(document, "docx"),
            output_path,
            {"paragraphs": document.get("paragraphs", []), "tables": original_data.get("tables", [])},
        )
    elif output_format == "md":
        MdParser.write(_render_text(document, "md"), output_path)
    elif output_format == "txt":
        TxtParser.write(_render_text(document, "txt"), output_path)
    elif output_format == "csv":
        _write_csv(original_data, output_path)
    elif output_format == "xlsx" and original_data.get("tables"):
        XlsxParser.write(original_data["tables"][0], output_path)

    return output_path


def _render_text(document: Dict[str, Any], output_format: str) -> str:
    lines = []
    for paragraph in document.get("paragraphs", []):
        text = paragraph.get("text", "")
        style = paragraph.get("style", "Normal")
        if output_format == "md" and style.startswith("Heading "):
            level = int(style.split()[-1])
            lines.append(f"{'#' * level} {_strip_heading_prefix(text)}")
        else:
            lines.append(text)
    separator = "\n\n" if output_format in {"md", "docx"} else "\n"
    return separator.join(lines)


def _write_csv(original_data: Dict[str, Any], output_path: str) -> None:
    rows = []
    sheets = original_data.get("sheets", [])
    if sheets:
        rows = sheets[0].get("data", [])
    with open(output_path, "w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        for row in rows:
            writer.writerow(row)


def _reindex_paragraphs(paragraphs: List[Dict[str, Any]]) -> None:
    for index, paragraph in enumerate(paragraphs):
        paragraph["index"] = index


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


def _make_change_record(op_name: str, index: int, before: str, after: str, reason: str) -> Dict[str, Any]:
    return {
        "op": op_name,
        "paragraph_index": index,
        "before": before[:300],
        "after": after[:300],
        "reason": reason,
    }


class ReplaceTextTool(BaseTool):
    """文本替换工具 - 替换文档中的指定文本"""

    @property
    def name(self) -> str:
        return "replace_text"

    @property
    def description(self) -> str:
        return "替换文档中的指定文本。需要提供文档ID、目标段落索引、要替换的原文本和新文本。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "old_text": {"type": "string", "description": "要替换的原文本"},
                "new_text": {"type": "string", "description": "替换后的新文本"},
                "reason": {"type": "string", "description": "替换原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "old_text", "new_text"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        # 获取文档路径
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        paragraph_index = params["paragraph_index"]
        paragraphs = structure.get("paragraphs", [])
        if not (0 <= paragraph_index < len(paragraphs)):
            return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围（共 {len(paragraphs)} 段）")

        paragraph = paragraphs[paragraph_index]
        old_text = params["old_text"]
        new_text = params["new_text"]
        before = paragraph["text"]
        paragraph["text"] = before.replace(old_text, new_text) if old_text else new_text

        output_file = _generate_output(structure, file_type, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已将第 {paragraph_index + 1} 段中的 '{old_text}' 替换为 '{new_text}'",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "changes": [_make_change_record("replace_text", paragraph_index, before, paragraph["text"], params.get("reason", ""))],
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        """获取文档路径（需要从数据库查询）"""
        # TODO: 实现从数据库查询文档路径
        # 这里简化处理，实际需要查询数据库
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class RewriteParagraphTool(BaseTool):
    """LLM重写段落工具 - 使用LLM重写指定段落"""

    @property
    def name(self) -> str:
        return "rewrite_paragraph"

    @property
    def description(self) -> str:
        return "使用LLM重写指定段落。需要提供文档ID、目标段落索引和重写指令。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "rewrite_instruction": {"type": "string", "description": "重写指令"},
                "reason": {"type": "string", "description": "重写原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "rewrite_instruction"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        paragraph_index = params["paragraph_index"]
        paragraphs = structure.get("paragraphs", [])
        if not (0 <= paragraph_index < len(paragraphs)):
            return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")

        paragraph = paragraphs[paragraph_index]
        before = paragraph["text"]
        rewrite_instruction = params.get("rewrite_instruction", "请重写此段落。")
        paragraph["text"] = await llm_service.rewrite_paragraph_text(before, rewrite_instruction)

        output_file = _generate_output(structure, file_type, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已重写第 {paragraph_index + 1} 段",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "changes": [_make_change_record("rewrite_paragraph", paragraph_index, before, paragraph["text"], params.get("reason", ""))],
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class InsertAfterTool(BaseTool):
    """段落后插入工具 - 在指定段落后插入新内容"""

    @property
    def name(self) -> str:
        return "insert_after"

    @property
    def description(self) -> str:
        return "在指定段落后插入新内容。需要提供文档ID、目标段落索引和要插入的文本。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "text": {"type": "string", "description": "要插入的文本"},
                "style": {"type": "string", "description": "段落样式（可选，默认Normal）"},
                "reason": {"type": "string", "description": "插入原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "text"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        paragraph_index = params["paragraph_index"]
        insert_text = params.get("text", "").strip()
        if not insert_text:
            return ToolResult(success=False, error="插入文本不能为空")

        style = params.get("style", "Normal")
        insert_at = paragraph_index + 1
        structure["paragraphs"].insert(insert_at, {"index": insert_at, "text": insert_text, "style": style})
        _reindex_paragraphs(structure["paragraphs"])

        output_file = _generate_output(structure, file_type, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已在第 {paragraph_index + 1} 段后插入新内容",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "changes": [_make_change_record("insert_after", insert_at, "", insert_text, params.get("reason", ""))],
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class HeadingPromoteTool(BaseTool):
    """标题级别调整工具 - 升级或降级标题"""

    @property
    def name(self) -> str:
        return "heading_promote"

    @property
    def description(self) -> str:
        return "调整标题级别。需要提供文档ID、目标段落索引和目标级别（1-6）。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "level": {"type": "integer", "description": "目标标题级别（1-6）"},
                "reason": {"type": "string", "description": "调整原因（可选）"},
            },
            "required": ["file_id", "paragraph_index", "level"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        paragraph_index = params["paragraph_index"]
        paragraphs = structure.get("paragraphs", [])
        if not (0 <= paragraph_index < len(paragraphs)):
            return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")

        paragraph = paragraphs[paragraph_index]
        before = f"[{paragraph['style']}] {paragraph['text']}"
        level = max(1, min(6, int(params.get("level", 1))))
        paragraph["style"] = f"Heading {level}"
        paragraph["text"] = _strip_heading_prefix(paragraph["text"])
        after = f"[{paragraph['style']}] {paragraph['text']}"

        output_file = _generate_output(structure, file_type, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已将第 {paragraph_index + 1} 段调整为 Heading {level}",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "changes": [_make_change_record("heading_promote", paragraph_index, before, after, params.get("reason", ""))],
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class ListFormatTool(BaseTool):
    """列表格式化工具 - 将文本转换为列表格式"""

    @property
    def name(self) -> str:
        return "list_format"

    @property
    def description(self) -> str:
        return "将指定段落转换为列表格式。需要提供文档ID、段落索引列表和列表类型（bullet/number）。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_indexes": {"type": "array", "items": {"type": "integer"}, "description": "段落索引列表"},
                "list_type": {"type": "string", "enum": ["bullet", "number"], "description": "列表类型"},
                "reason": {"type": "string", "description": "格式化原因（可选）"},
            },
            "required": ["file_id", "paragraph_indexes", "list_type"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        paragraphs = structure.get("paragraphs", [])
        indexes = params.get("paragraph_indexes", [])
        list_type = params.get("list_type", "bullet")
        changes = []

        for position, index in enumerate(indexes, start=1):
            if not (0 <= index < len(paragraphs)):
                continue
            paragraph = paragraphs[index]
            before = paragraph["text"]
            clean_text = _strip_list_prefix(before)
            if list_type == "number":
                paragraph["text"] = f"{position}. {clean_text}"
                paragraph["style"] = "List Number"
            else:
                paragraph["text"] = f"- {clean_text}"
                paragraph["style"] = "List Bullet"
            changes.append(_make_change_record("list_format", index, before, paragraph["text"], params.get("reason", "")))

        output_file = _generate_output(structure, file_type, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已将 {len(changes)} 个段落格式化为{'有序' if list_type == 'number' else '无序'}列表",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "changes": changes,
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class ParagraphSplitTool(BaseTool):
    """段落拆分工具 - 将长段落拆分为多个段落"""

    @property
    def name(self) -> str:
        return "paragraph_split"

    @property
    def description(self) -> str:
        return "将指定段落拆分为多个段落。需要提供文档ID、目标段落索引和可选的分隔符。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_index": {"type": "integer", "description": "目标段落索引（从0开始）"},
                "separator": {"type": "string", "description": "分隔符（可选，默认按句号拆分）"},
                "reason": {"type": "string", "description": "拆分原因（可选）"},
            },
            "required": ["file_id", "paragraph_index"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        paragraph_index = params["paragraph_index"]
        paragraphs = structure.get("paragraphs", [])
        if not (0 <= paragraph_index < len(paragraphs)):
            return ToolResult(success=False, error=f"段落索引 {paragraph_index} 超出范围")

        paragraph = paragraphs[paragraph_index]
        separator = params.get("separator")
        parts = _split_paragraph(paragraph["text"], separator)
        if len(parts) <= 1:
            return ToolResult(success=True, data={"message": "段落无法拆分（未找到分隔点）"})

        before = paragraph["text"]
        paragraph["text"] = parts[0]
        for offset, part in enumerate(parts[1:], start=1):
            paragraphs.insert(
                paragraph_index + offset,
                {"index": paragraph_index + offset, "text": part, "style": paragraph["style"]},
            )
        _reindex_paragraphs(paragraphs)

        output_file = _generate_output(structure, file_type, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已将第 {paragraph_index + 1} 段拆分为 {len(parts)} 个段落",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "changes": [_make_change_record("paragraph_split", paragraph_index, before, "\n".join(parts), params.get("reason", ""))],
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class SetTextStyleTool(BaseTool):
    """字体样式设置工具 - 设置文本的字体、大小等样式"""

    @property
    def name(self) -> str:
        return "set_text_style"

    @property
    def description(self) -> str:
        return "设置指定段落的字体样式。需要提供文档ID、段落索引和字体名称或大小。仅支持docx文件。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文档ID"},
                "paragraph_indexes": {"type": "array", "items": {"type": "integer"}, "description": "段落索引列表"},
                "font_name": {"type": "string", "description": "字体名称（可选）"},
                "font_size_pt": {"type": "number", "description": "字体大小（pt，可选）"},
                "reason": {"type": "string", "description": "设置原因（可选）"},
            },
            "required": ["file_id", "paragraph_indexes"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        if file_type != "docx":
            return ToolResult(success=False, error="字体样式设置仅支持docx文件")

        doc = DocxParser.load_document(doc_path)
        all_paragraphs = list(doc.paragraphs)
        source_indexes = params.get("paragraph_indexes", [])
        font_name = params.get("font_name", "")
        font_size_pt = params.get("font_size_pt")
        changes = []

        for index in source_indexes:
            if not (0 <= index < len(all_paragraphs)):
                continue
            paragraph = all_paragraphs[index]
            before = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
            DocxParser.set_paragraph_font(paragraph, font_name=font_name, font_size_pt=font_size_pt)
            after = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
            changes.append(_make_change_record("set_text_style", index, before, after, params.get("reason", "")))

        output_filename = f"output_{uuid4().hex}.docx"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        DocxParser.save_document(doc, output_path)

        return ToolResult(
            success=True,
            data={
                "message": f"已设置 {len(changes)} 个段落的字体样式",
                "output_file": output_path,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_path)}",
                "changes": changes,
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None


class ConvertTool(BaseTool):
    """格式转换工具 - 文档格式转换（docx<->md, xlsx<->csv）"""

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
        doc_path = self._get_doc_path(params["file_id"])
        if not doc_path:
            return ToolResult(success=False, error=f"文档 {params['file_id']} 不存在")

        file_type = doc_path.rsplit(".", 1)[-1].lower()
        target_format = params.get("target_format", "").lower()

        if target_format not in CONVERT_RULES.get(file_type, set()):
            return ToolResult(success=False, error=f"不支持从 {file_type} 转换为 {target_format}")

        parser = _get_parser(file_type)
        if not parser:
            return ToolResult(success=False, error=f"不支持的文件类型: {file_type}")

        parsed_data = parser.parse(doc_path)
        structure = _build_editable_structure(parsed_data, file_type)

        output_file = _generate_output(structure, target_format, parsed_data)

        return ToolResult(
            success=True,
            data={
                "message": f"已将文档从 {file_type} 转换为 {target_format}",
                "output_file": output_file,
                "download_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "output_format": target_format,
            },
        )

    def _get_doc_path(self, file_id: str) -> Optional[str]:
        upload_dir = settings.UPLOAD_DIR
        for fname in os.listdir(upload_dir):
            if fname.startswith(file_id):
                return os.path.join(upload_dir, fname)
        return None
