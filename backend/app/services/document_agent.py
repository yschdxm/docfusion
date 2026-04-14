import copy
import csv
import logging
import os
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.core.config import get_settings
from app.services.document_processor import DocxParser, MdParser, TxtParser, XlsxParser
from app.services.llm_service import llm_service
from app.services.table_filling_service import table_filling_service

logger = logging.getLogger(__name__)
settings = get_settings()

SUPPORTED_PLAN_OPS = {
    "replace_text",
    "rewrite_paragraph",
    "insert_after",
    "heading_promote",
    "list_format",
    "paragraph_split",
    "convert",
}

CONVERT_RULES = {
    "docx": {"md", "txt"},
    "md": {"docx", "txt"},
    "txt": {"md", "docx"},
    "xlsx": {"csv"},
}


class DocumentAgent:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "md": MdParser(),
            "txt": TxtParser(),
        }

    async def process_instruction(
        self,
        intent: str,
        documents_content: List[Dict[str, Any]],
        template_content: Optional[Dict[str, Any]] = None,
        instruction: str = "",
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            if action_id and action_id.startswith("fill-"):
                return await self._execute_table_fill(documents_content, template_content)

            if intent == "fill_table":
                return await self._execute_table_fill(documents_content, template_content, instruction)
            if intent == "operation":
                return await self._execute_document_operation(documents_content, instruction)
            return {"success": False, "message": "未知操作类型"}
        except Exception as exc:
            logger.error("Instruction processing failed: intent=%s error=%s", intent, exc)
            return {"success": False, "message": f"操作失败: {str(exc)}"}

    async def _execute_table_fill(
        self,
        documents_content: List[Dict[str, Any]],
        template_content: Optional[Dict[str, Any]],
        instruction: str = "智能填写表格",
    ) -> Dict[str, Any]:
        try:
            if not template_content:
                return {"success": False, "message": "缺少模板文件。"}

            source_files = [{"file_type": d["file_type"], "file_path": d.get("file_path", "")} for d in documents_content]
            template_file = {"file_type": template_content["file_type"], "file_path": template_content.get("file_path", "")}

            if template_content["file_type"] == "xlsx":
                fill_result = await table_filling_service.fill_table(
                    source_files=source_files,
                    template_file=template_file,
                    user_instruction=instruction,
                )
            else:
                fill_result = await table_filling_service.fill_word_template(
                    source_files=source_files,
                    template_file=template_file,
                    user_instruction=instruction,
                )

            return {
                "success": True,
                "message": "表格填写完成，已生成结果文件。",
                "action": {
                    "action_id": "",
                    "action_type": "completed",
                    "title": "表格填写完成",
                    "description": f"已完成模板 {template_content.get('filename', '')} 的填写",
                    "progress": 100,
                    "result": {
                        "filled_file_url": f"/api/v1/table-fill/download-file/{fill_result.get('output_filename', '')}",
                        "output_filename": fill_result.get("output_filename", ""),
                    },
                },
            }
        except Exception as exc:
            logger.error("Table fill failed: error=%s", exc)
            return {
                "success": False,
                "message": f"表格填写失败: {str(exc)}",
                "action": {
                    "action_id": "",
                    "action_type": "failed",
                    "title": "表格填写失败",
                    "description": str(exc),
                },
            }

    async def _execute_document_operation(
        self,
        documents_content: List[Dict[str, Any]],
        instruction: str,
    ) -> Dict[str, Any]:
        if not documents_content:
            return {"success": False, "message": "请先选择要操作的文档。"}

        doc = documents_content[0]
        file_path = doc.get("file_path", "")
        file_type = doc.get("file_type", "")

        parser = self.parsers.get(file_type)
        if not parser:
            return {"success": False, "message": f"暂不支持该文件类型: {file_type}"}

        parsed_data = parser.parse(file_path)
        original_structure = self._build_editable_structure(parsed_data, file_type)
        plan = await llm_service.plan_document_operations(original_structure, instruction, file_type)
        validated_plan = self._validate_plan(plan, original_structure, file_type)

        if not validated_plan["operations"]:
            return {
                "success": False,
                "message": validated_plan.get("message", "没有生成可执行的操作计划。"),
                "action": {
                    "action_id": "",
                    "action_type": "failed",
                    "title": "未生成可执行计划",
                    "description": validated_plan.get("summary", "操作计划为空"),
                    "result": {"plan": validated_plan},
                },
            }

        if self._can_use_docx_inplace(file_type, validated_plan["operations"]):
            execution_result = await self._execute_docx_operations_in_place(
                file_path=file_path,
                operations=validated_plan["operations"],
            )
        else:
            execution_result = await self._execute_operations(copy.deepcopy(original_structure), validated_plan["operations"], file_type)

        output_format = execution_result.get("output_format", file_type)
        output_file = execution_result.get("output_file")
        if not output_file:
            output_file = self._generate_output(execution_result["document"], output_format, parsed_data)
        preview = self._generate_preview(execution_result["changes"])

        return {
            "success": True,
            "message": validated_plan.get("message", "文档操作完成"),
            "result": {
                "plan": validated_plan,
                "preview": preview,
                "output_file": output_file,
                "filled_file_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                "output_format": output_format,
            },
            "action": {
                "action_id": "",
                "action_type": "completed",
                "title": "文档操作完成",
                "description": validated_plan.get("summary", "已完成文档操作计划执行"),
                "progress": 100,
                "result": {
                    "plan": validated_plan,
                    "preview": preview,
                    "output_file": output_file,
                    "output_filename": os.path.basename(output_file),
                    "filled_file_url": f"/api/v1/agent/download-file/{os.path.basename(output_file)}",
                    "output_format": output_format,
                },
            },
        }

    def _can_use_docx_inplace(self, file_type: str, operations: List[Dict[str, Any]]) -> bool:
        if file_type != "docx":
            return False
        supported_ops = {"replace_text", "rewrite_paragraph", "insert_after", "heading_promote"}
        return all(operation.get("op") in supported_ops for operation in operations)

    def _build_editable_structure(self, parsed_data: Dict[str, Any], file_type: str) -> Dict[str, Any]:
        paragraphs: List[Dict[str, Any]] = []

        if file_type == "docx":
            for paragraph in parsed_data.get("paragraphs", []):
                text = (paragraph.get("text") or "").strip()
                if not text:
                    continue
                paragraphs.append(
                    {
                        "index": len(paragraphs),
                        "text": text,
                        "style": paragraph.get("style") or "Normal",
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
                        "text": f"工作表 {sheet.get('name', sheet_idx)}，共 {sheet.get('rows', 0)} 行 {sheet.get('cols', 0)} 列",
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

    def _validate_plan(self, plan: Dict[str, Any], document_structure: Dict[str, Any], file_type: str) -> Dict[str, Any]:
        paragraphs = document_structure.get("paragraphs", [])
        paragraph_count = len(paragraphs)
        validated_ops = []

        for operation in plan.get("operations", []):
            op_name = operation.get("op")
            if op_name not in SUPPORTED_PLAN_OPS:
                continue

            target = operation.get("target") or {}
            params = operation.get("params") or {}
            paragraph_index = target.get("paragraph_index")
            paragraph_indexes = target.get("paragraph_indexes") or []

            if paragraph_index is not None:
                try:
                    paragraph_index = int(paragraph_index)
                except (TypeError, ValueError):
                    continue
                if not (0 <= paragraph_index < paragraph_count):
                    continue
                target["paragraph_index"] = paragraph_index

            if paragraph_indexes:
                cleaned_indexes = []
                for index in paragraph_indexes:
                    try:
                        paragraph_value = int(index)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= paragraph_value < paragraph_count:
                        cleaned_indexes.append(paragraph_value)
                if not cleaned_indexes:
                    continue
                target["paragraph_indexes"] = cleaned_indexes

            if op_name == "convert":
                target_format = (params.get("target_format") or "").lower()
                if target_format not in CONVERT_RULES.get(file_type, set()):
                    continue
                params["target_format"] = target_format

            validated_ops.append(
                {
                    "op": op_name,
                    "target": target,
                    "params": params,
                    "reason": operation.get("reason", ""),
                }
            )

        return {
            "intent": plan.get("intent", "document_operation"),
            "document_type": file_type,
            "summary": plan.get("summary", "已生成操作计划"),
            "need_confirm": False,
            "response_mode": plan.get("response_mode", "preview"),
            "message": plan.get("message", "已根据指令生成操作计划"),
            "operations": validated_ops,
        }

    async def _execute_operations(
        self,
        document: Dict[str, Any],
        operations: List[Dict[str, Any]],
        file_type: str,
    ) -> Dict[str, Any]:
        output_format = file_type
        changes: List[Dict[str, Any]] = []

        for operation in operations:
            op_name = operation["op"]
            target = operation.get("target", {})
            params = operation.get("params", {})

            if op_name == "replace_text":
                index = int(target["paragraph_index"])
                paragraph = document["paragraphs"][index]
                old_text = params.get("old_text", "")
                new_text = params.get("new_text", "")
                before = paragraph["text"]
                paragraph["text"] = before.replace(old_text, new_text) if old_text else new_text
                changes.append(self._make_change_record(op_name, index, before, paragraph["text"], operation.get("reason", "")))

            elif op_name == "rewrite_paragraph":
                index = int(target["paragraph_index"])
                paragraph = document["paragraphs"][index]
                before = paragraph["text"]
                rewrite_instruction = params.get("rewrite_instruction", "请优化这段内容")
                paragraph["text"] = await llm_service.rewrite_paragraph_text(before, rewrite_instruction)
                changes.append(self._make_change_record(op_name, index, before, paragraph["text"], operation.get("reason", "")))

            elif op_name == "insert_after":
                index = int(target["paragraph_index"])
                insert_text = params.get("text", "").strip()
                if not insert_text:
                    continue
                style = params.get("style", "Normal")
                insert_at = index + 1
                document["paragraphs"].insert(insert_at, {"index": insert_at, "text": insert_text, "style": style})
                self._reindex_paragraphs(document["paragraphs"])
                changes.append(self._make_change_record(op_name, insert_at, "", insert_text, operation.get("reason", "")))

            elif op_name == "heading_promote":
                index = int(target["paragraph_index"])
                paragraph = document["paragraphs"][index]
                before = f"[{paragraph['style']}] {paragraph['text']}"
                level = max(1, min(6, int(params.get("level", 1))))
                paragraph["style"] = f"Heading {level}"
                paragraph["text"] = self._strip_heading_prefix(paragraph["text"])
                after = f"[{paragraph['style']}] {paragraph['text']}"
                changes.append(self._make_change_record(op_name, index, before, after, operation.get("reason", "")))

            elif op_name == "list_format":
                indexes = [int(idx) for idx in target.get("paragraph_indexes", [])]
                list_type = params.get("list_type", "bullet")
                for position, index in enumerate(indexes, start=1):
                    paragraph = document["paragraphs"][index]
                    before = paragraph["text"]
                    clean_text = self._strip_list_prefix(before)
                    if list_type == "number":
                        paragraph["text"] = f"{position}. {clean_text}"
                        paragraph["style"] = "List Number"
                    else:
                        paragraph["text"] = f"- {clean_text}"
                        paragraph["style"] = "List Bullet"
                    changes.append(self._make_change_record(op_name, index, before, paragraph["text"], operation.get("reason", "")))

            elif op_name == "paragraph_split":
                index = int(target["paragraph_index"])
                paragraph = document["paragraphs"][index]
                separator = params.get("separator")
                parts = self._split_paragraph(paragraph["text"], separator)
                if len(parts) <= 1:
                    continue
                before = paragraph["text"]
                paragraph["text"] = parts[0]
                for offset, part in enumerate(parts[1:], start=1):
                    document["paragraphs"].insert(
                        index + offset,
                        {"index": index + offset, "text": part, "style": paragraph["style"]},
                    )
                self._reindex_paragraphs(document["paragraphs"])
                changes.append(self._make_change_record(op_name, index, before, "\n".join(parts), operation.get("reason", "")))

            elif op_name == "convert":
                output_format = params.get("target_format", output_format)
                changes.append(self._make_change_record(op_name, -1, file_type, output_format, operation.get("reason", "")))

        return {"document": document, "output_format": output_format, "changes": changes}

    async def _execute_docx_operations_in_place(
        self,
        file_path: str,
        operations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        doc = DocxParser.load_document(file_path)
        content_paragraphs = DocxParser.get_content_paragraphs(doc)
        changes: List[Dict[str, Any]] = []
        output_path = os.path.join(settings.UPLOAD_DIR, "output", f"output_{uuid4().hex}.docx")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        for operation in operations:
            op_name = operation["op"]
            target = operation.get("target", {})
            params = operation.get("params", {})
            paragraph_index = int(target["paragraph_index"])

            if not (0 <= paragraph_index < len(content_paragraphs)):
                continue

            paragraph = content_paragraphs[paragraph_index]

            if op_name == "replace_text":
                old_text = params.get("old_text", "")
                new_text = params.get("new_text", "")
                before = DocxParser.replace_text_in_paragraph(paragraph, old_text, new_text)
                changes.append(
                    self._make_change_record(op_name, paragraph_index, before, paragraph.text, operation.get("reason", ""))
                )

            elif op_name == "rewrite_paragraph":
                rewrite_instruction = params.get("rewrite_instruction", "请优化这段内容")
                before = paragraph.text
                rewritten_text = await llm_service.rewrite_paragraph_text(before, rewrite_instruction)
                DocxParser.rewrite_paragraph(paragraph, rewritten_text)
                changes.append(
                    self._make_change_record(op_name, paragraph_index, before, paragraph.text, operation.get("reason", ""))
                )

            elif op_name == "insert_after":
                insert_text = params.get("text", "").strip()
                if not insert_text:
                    continue
                style_name = params.get("style")
                inserted_paragraph = DocxParser.insert_paragraph_after(paragraph, insert_text, style_name)
                content_paragraphs.insert(paragraph_index + 1, inserted_paragraph)
                changes.append(
                    self._make_change_record(op_name, paragraph_index + 1, "", inserted_paragraph.text, operation.get("reason", ""))
                )

            elif op_name == "heading_promote":
                level = int(params.get("level", 1))
                before = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
                DocxParser.promote_heading(paragraph, level)
                after = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
                changes.append(
                    self._make_change_record(op_name, paragraph_index, before, after, operation.get("reason", ""))
                )

        DocxParser.save_document(doc, output_path)
        return {"output_format": "docx", "output_file": output_path, "changes": changes}

    def _generate_preview(self, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"total_changes": len(changes), "items": changes[:10]}

    def _generate_output(self, document: Dict[str, Any], output_format: str, original_data: Dict[str, Any]) -> str:
        output_filename = f"output_{uuid4().hex}.{output_format}"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if output_format == "docx":
            DocxParser.write(
                self._render_text(document, "docx"),
                output_path,
                {"paragraphs": document.get("paragraphs", []), "tables": original_data.get("tables", [])},
            )
        elif output_format == "md":
            MdParser.write(self._render_text(document, "md"), output_path)
        elif output_format == "txt":
            TxtParser.write(self._render_text(document, "txt"), output_path)
        elif output_format == "csv":
            self._write_csv(original_data, output_path)
        elif output_format == "xlsx" and original_data.get("tables"):
            XlsxParser.write(original_data["tables"][0], output_path)

        return output_path

    def _render_text(self, document: Dict[str, Any], output_format: str) -> str:
        lines = []
        for paragraph in document.get("paragraphs", []):
            text = paragraph.get("text", "")
            style = paragraph.get("style", "Normal")
            if output_format == "md" and style.startswith("Heading "):
                level = int(style.split()[-1])
                lines.append(f"{'#' * level} {self._strip_heading_prefix(text)}")
            else:
                lines.append(text)
        separator = "\n\n" if output_format in {"md", "docx"} else "\n"
        return separator.join(lines)

    def _write_csv(self, original_data: Dict[str, Any], output_path: str) -> None:
        rows = []
        sheets = original_data.get("sheets", [])
        if sheets:
            rows = sheets[0].get("data", [])
        with open(output_path, "w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.writer(csv_file)
            for row in rows:
                writer.writerow(row)

    def _make_change_record(self, op_name: str, index: int, before: str, after: str, reason: str) -> Dict[str, Any]:
        return {
            "op": op_name,
            "paragraph_index": index,
            "before": before[:300],
            "after": after[:300],
            "reason": reason,
        }

    def _reindex_paragraphs(self, paragraphs: List[Dict[str, Any]]) -> None:
        for index, paragraph in enumerate(paragraphs):
            paragraph["index"] = index

    def _split_paragraph(self, text: str, separator: Optional[str]) -> List[str]:
        if separator:
            parts = [part.strip() for part in text.split(separator) if part.strip()]
            return parts or [text]
        parts = [part.strip() for part in re.split(r"(?<=[。！？；;.!?])", text) if part.strip()]
        return parts or [text]

    def _strip_heading_prefix(self, text: str) -> str:
        return re.sub(r"^#{1,6}\s+", "", text).strip()

    def _strip_list_prefix(self, text: str) -> str:
        return re.sub(r"^(?:[-*]|\d+\.)\s+", "", text).strip()


document_agent = DocumentAgent()
