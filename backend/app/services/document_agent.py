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
    "set_text_style",
    "convert",
}

NUMBER_TOKEN_PATTERN = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\w.])")
PARAGRAPH_LAST_SENTENCE_DELETE_PATTERN = re.compile(r"\u5220\u9664\u7b2c\s*([0-9]+)\s*\u6bb5\u6700\u540e\u4e00\u53e5\u8bdd")
DECIMAL_PLACES_PATTERN = re.compile(
    r"(?:\u4fdd\u7559|\u7edf\u4e00\u4e3a|\u5c0f\u6570\u70b9\u540e|keep|round to|to)\s*([0-9]{1,2})\s*(?:\u4f4d\u5c0f\u6570|decimal(?:s| places)?|dp)?",
    re.IGNORECASE,
)
CHINESE_DECIMAL_PLACES_PATTERN = re.compile(r"([\u96f6\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]{1,3})\s*\u4f4d\u5c0f\u6570")
HEADING_STYLE_KEYWORDS = ("heading", "\u6807\u9898", "title", "subtitle")
FONT_NAME_KEYWORDS = (
    "\u5b8b\u4f53",
    "\u9ed1\u4f53",
    "\u4eff\u5b8b",
    "\u6977\u4f53",
    "\u5fae\u8f6f\u96c5\u9ed1",
    "times new roman",
    "arial",
)
FONT_SIZE_ALIASES = {
    "\u521d\u53f7": 42.0,
    "\u5c0f\u521d": 36.0,
    "\u4e00\u53f7": 26.0,
    "\u5c0f\u4e00": 24.0,
    "\u4e8c\u53f7": 22.0,
    "\u5c0f\u4e8c": 18.0,
    "\u4e09\u53f7": 16.0,
    "\u5c0f\u4e09": 15.0,
    "\u56db\u53f7": 14.0,
    "\u5c0f\u56db": 12.0,
    "\u4e94\u53f7": 10.5,
    "\u5c0f\u4e94": 9.0,
    "\u516d\u53f7": 7.5,
    "\u5c0f\u516d": 6.5,
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
            return {"success": False, "message": "Unknown operation intent."}
        except Exception as exc:
            logger.error("Instruction processing failed: intent=%s error=%s", intent, exc)
            return {"success": False, "message": f"Operation failed: {str(exc)}"}

    async def _execute_table_fill(
        self,
        documents_content: List[Dict[str, Any]],
        template_content: Optional[Dict[str, Any]],
        instruction: str = "",
    ) -> Dict[str, Any]:
        try:
            if not template_content:
                return {"success": False, "message": "Missing template file."}

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
                "message": "Table filling completed and output file generated.",
                "action": {
                    "action_id": "",
                    "action_type": "completed",
                    "title": "Table filling completed",
                    "description": f"Template {template_content.get('filename', '')} has been filled.",
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
                "message": f"Table filling failed: {str(exc)}",
                "action": {
                    "action_id": "",
                    "action_type": "failed",
                    "title": "Table filling failed",
                    "description": str(exc),
                },
            }

    async def _execute_document_operation(
        self,
        documents_content: List[Dict[str, Any]],
        instruction: str,
    ) -> Dict[str, Any]:
        if not documents_content:
            return {"success": False, "message": "Please select a document first."}

        doc = documents_content[0]
        file_path = doc.get("file_path", "")
        file_type = doc.get("file_type", "")

        parser = self.parsers.get(file_type)
        if not parser:
            return {"success": False, "message": f"Unsupported file type: {file_type}"}

        parsed_data = parser.parse(file_path)
        original_structure = self._build_editable_structure(parsed_data, file_type)
        plan = await llm_service.plan_document_operations(original_structure, instruction, file_type)
        validated_plan = self._validate_plan(plan, original_structure, file_type, instruction)
        if not validated_plan["operations"]:
            fallback_plan = self._build_fallback_plan(original_structure, instruction, file_type)
            if fallback_plan:
                validated_plan = fallback_plan

        if not validated_plan["operations"]:
            return {
                "success": False,
                "message": validated_plan.get("message", "No executable operation plan was generated."),
                "action": {
                    "action_id": "",
                    "action_type": "failed",
                    "title": "No executable plan generated",
                    "description": validated_plan.get("summary", "Operation plan is empty"),
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
            "message": validated_plan.get("message", "Document operation completed."),
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
                "title": "Document operation completed",
                "description": validated_plan.get("summary", "Document operations executed."),
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
        supported_ops = {"replace_text", "rewrite_paragraph", "insert_after", "heading_promote", "set_text_style"}
        return all(operation.get("op") in supported_ops for operation in operations)

    def _build_editable_structure(self, parsed_data: Dict[str, Any], file_type: str) -> Dict[str, Any]:
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
                if not self._is_heading_style(style_name):
                    body_candidates.append(item)
            # "第N段"默认指正文段落，避免把标题当成正文段被误删。
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

    def _build_fallback_plan(
        self,
        document_structure: Dict[str, Any],
        instruction: str,
        file_type: str,
    ) -> Optional[Dict[str, Any]]:
        delete_last_sentence_plan = self._build_delete_last_sentence_plan(document_structure, instruction, file_type)
        if delete_last_sentence_plan:
            return delete_last_sentence_plan

        body_font_plan = self._build_body_font_plan(document_structure, instruction, file_type)
        if body_font_plan:
            return body_font_plan

        decimal_places = self._extract_decimal_places_instruction(instruction)
        if decimal_places is not None:
            operations = self._build_decimal_replace_ops(document_structure.get("paragraphs", []), decimal_places)
            return {
                "intent": "document_operation",
                "document_type": file_type,
                "summary": f"Rule-based plan generated for number normalization ({decimal_places} decimals).",
                "need_confirm": False,
                "response_mode": "preview",
                "message": f"Applied by rule engine: numbers normalized to {decimal_places} decimals.",
                "operations": operations,
            }
        return None

    def _build_body_font_plan(
        self,
        document_structure: Dict[str, Any],
        instruction: str,
        file_type: str,
    ) -> Optional[Dict[str, Any]]:
        if file_type != "docx":
            return None
        style_request = self._extract_font_style_request(instruction)
        if not style_request:
            return None

        paragraphs = document_structure.get("paragraphs", [])
        if not paragraphs:
            return None

        paragraph_indexes = [paragraph["index"] for paragraph in paragraphs if paragraph.get("index") is not None]
        source_paragraph_indexes = [
            int(paragraph["source_paragraph_index"])
            for paragraph in paragraphs
            if paragraph.get("source_paragraph_index") is not None
        ]
        if not paragraph_indexes:
            return None

        params: Dict[str, Any] = {}
        if style_request.get("font_name"):
            params["font_name"] = style_request["font_name"]
        if style_request.get("font_size_pt") is not None:
            params["font_size_pt"] = style_request["font_size_pt"]
        if not params:
            return None

        target: Dict[str, Any] = {
            "paragraph_index": paragraph_indexes[0],
            "paragraph_indexes": paragraph_indexes,
        }
        if source_paragraph_indexes:
            target["source_paragraph_indexes"] = source_paragraph_indexes

        return {
            "intent": "document_operation",
            "document_type": file_type,
            "summary": "Rule-based plan generated for body text style.",
            "need_confirm": False,
            "response_mode": "preview",
            "message": "Applied by rule engine: body font and size updated.",
            "operations": [
                {
                    "op": "set_text_style",
                    "target": target,
                    "params": params,
                    "reason": "Normalize body text style",
                }
            ],
        }

    def _extract_font_style_request(self, instruction: str) -> Optional[Dict[str, Any]]:
        normalized = instruction.strip()
        normalized_lower = normalized.lower()
        if ("\u6b63\u6587" not in normalized) and ("\u5168\u6587" not in normalized):
            return None

        font_name = ""
        for keyword in FONT_NAME_KEYWORDS:
            if keyword in normalized_lower:
                font_name = keyword if keyword in {"times new roman", "arial"} else keyword
                if keyword == "times new roman":
                    font_name = "Times New Roman"
                elif keyword == "arial":
                    font_name = "Arial"
                break

        font_size_pt = None
        for alias, size_pt in FONT_SIZE_ALIASES.items():
            if alias in normalized:
                font_size_pt = size_pt
                break
        if font_size_pt is None:
            direct_pt = re.search(r"(\d+(?:\.\d+)?)\s*(?:pt|\u78c5)", normalized_lower)
            if direct_pt:
                font_size_pt = float(direct_pt.group(1))

        if not font_name and font_size_pt is None:
            return None
        return {"font_name": font_name, "font_size_pt": font_size_pt}

    def _build_delete_last_sentence_plan(
        self,
        document_structure: Dict[str, Any],
        instruction: str,
        file_type: str,
    ) -> Optional[Dict[str, Any]]:
        if file_type != "docx":
            return None
        match = PARAGRAPH_LAST_SENTENCE_DELETE_PATTERN.search(
            instruction.replace("\u3002", "").replace("\uff01", "").replace("\uff1f", "")
        )
        if not match:
            return None

        paragraph_order = int(match.group(1))
        paragraphs = document_structure.get("paragraphs", [])
        paragraph_index = paragraph_order - 1
        if not (0 <= paragraph_index < len(paragraphs)):
            return None

        paragraph_text = (paragraphs[paragraph_index].get("text") or "").strip()
        if not paragraph_text:
            return None
        sentences = self._split_paragraph(paragraph_text, None)
        if len(sentences) <= 1:
            return None

        last_sentence = sentences[-1]
        new_text = paragraph_text[: paragraph_text.rfind(last_sentence)].rstrip()
        if not new_text:
            return None

        return {
            "intent": "document_operation",
            "document_type": file_type,
            "summary": "Rule-based plan generated for sentence deletion.",
            "need_confirm": False,
            "response_mode": "preview",
            "message": "Applied by rule engine: deleted the last sentence in the target paragraph.",
            "operations": [
                {
                    "op": "replace_text",
                    "target": {"paragraph_index": paragraph_index},
                    "params": {"old_text": paragraph_text, "new_text": new_text},
                    "reason": "Delete the last sentence of the specified paragraph",
                }
            ],
        }

    def _extract_decimal_places_instruction(self, instruction: str) -> Optional[int]:
        normalized = instruction.strip()
        if not normalized:
            return None

        direct_match = DECIMAL_PLACES_PATTERN.search(normalized)
        if direct_match:
            return self._clamp_decimal_places(int(direct_match.group(1)))

        chinese_match = CHINESE_DECIMAL_PLACES_PATTERN.search(normalized)
        if chinese_match:
            chinese_value = self._chinese_number_to_int(chinese_match.group(1))
            if chinese_value is not None:
                return self._clamp_decimal_places(chinese_value)
        return None

    def _build_decimal_replace_ops(self, paragraphs: List[Dict[str, Any]], decimal_places: int) -> List[Dict[str, Any]]:
        operations: List[Dict[str, Any]] = []
        for paragraph in paragraphs:
            paragraph_index = paragraph.get("index")
            text = paragraph.get("text") or ""
            if paragraph_index is None or not text:
                continue

            paragraph_ops = []
            seen_pairs = set()
            for token in NUMBER_TOKEN_PATTERN.findall(text):
                formatted = self._format_number_to_decimals(token, decimal_places)
                if not formatted or formatted == token:
                    continue
                pair = (token, formatted)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                paragraph_ops.append(
                    {
                        "op": "replace_text",
                        "target": {"paragraph_index": int(paragraph_index)},
                        "params": {"old_text": token, "new_text": formatted},
                        "reason": f"Normalize numbers to {decimal_places} decimal places",
                    }
                )

            operations.extend(paragraph_ops)
        return operations

    def _format_number_to_decimals(self, token: str, decimal_places: int) -> str:
        normalized = token.replace(",", "")
        try:
            number = float(normalized)
        except ValueError:
            return token
        decimal_places = self._clamp_decimal_places(decimal_places)
        if "," in token:
            return format(number, f",.{decimal_places}f")
        return format(number, f".{decimal_places}f")

    def _clamp_decimal_places(self, decimal_places: int) -> int:
        return max(0, min(10, int(decimal_places)))

    def _chinese_number_to_int(self, value: str) -> Optional[int]:
        mapping = {
            "\u96f6": 0,
            "\u4e00": 1,
            "\u4e8c": 2,
            "\u4e24": 2,
            "\u4e09": 3,
            "\u56db": 4,
            "\u4e94": 5,
            "\u516d": 6,
            "\u4e03": 7,
            "\u516b": 8,
            "\u4e5d": 9,
            "\u5341": 10,
        }
        if value in mapping:
            return mapping[value]
        if value.startswith("\u5341") and len(value) == 2 and value[1] in mapping:
            return 10 + mapping[value[1]]
        if value.endswith("\u5341") and len(value) == 2 and value[0] in mapping:
            return mapping[value[0]] * 10
        if len(value) == 3 and value[1] == "\u5341" and value[0] in mapping and value[2] in mapping:
            return mapping[value[0]] * 10 + mapping[value[2]]
        return None

    def _validate_plan(
        self,
        plan: Dict[str, Any],
        document_structure: Dict[str, Any],
        file_type: str,
        instruction: str = "",
    ) -> Dict[str, Any]:
        paragraphs = document_structure.get("paragraphs", [])
        paragraph_count = len(paragraphs)
        validated_ops = []
        paragraph_mode = "paragraph" in instruction
        heading_mode = ("\u6807\u9898" in instruction) or ("heading" in instruction.lower())

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
                source_paragraph_index = paragraphs[paragraph_index].get("source_paragraph_index")
                if source_paragraph_index is not None:
                    target["source_paragraph_index"] = int(source_paragraph_index)

                # Avoid touching heading paragraphs when user asks for "paragraph N" edits.
                if file_type == "docx" and paragraph_mode and not heading_mode:
                    paragraph_style = (paragraphs[paragraph_index].get("style") or "").strip()
                    if self._is_heading_style(paragraph_style):
                        continue

            if paragraph_indexes:
                cleaned_indexes = []
                source_indexes = []
                for index in paragraph_indexes:
                    try:
                        paragraph_value = int(index)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= paragraph_value < paragraph_count:
                        cleaned_indexes.append(paragraph_value)
                        source_paragraph_index = paragraphs[paragraph_value].get("source_paragraph_index")
                        if source_paragraph_index is not None:
                            source_indexes.append(int(source_paragraph_index))
                if not cleaned_indexes:
                    continue
                target["paragraph_indexes"] = cleaned_indexes
                if source_indexes:
                    target["source_paragraph_indexes"] = source_indexes

            if op_name == "convert":
                target_format = (params.get("target_format") or "").lower()
                if target_format not in CONVERT_RULES.get(file_type, set()):
                    continue
                params["target_format"] = target_format
            elif op_name == "set_text_style":
                if file_type != "docx":
                    continue
                has_font_name = bool((params.get("font_name") or "").strip())
                has_font_size = params.get("font_size_pt") is not None
                if not (has_font_name or has_font_size):
                    continue

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
            "summary": plan.get("summary", "Operation plan generated."),
            "need_confirm": False,
            "response_mode": plan.get("response_mode", "preview"),
            "message": plan.get("message", "Operation plan generated from instruction."),
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
                rewrite_instruction = params.get("rewrite_instruction", "Please rewrite this paragraph.")
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
        all_paragraphs = list(doc.paragraphs)
        changes: List[Dict[str, Any]] = []
        output_path = os.path.join(settings.UPLOAD_DIR, "output", f"output_{uuid4().hex}.docx")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        for operation in operations:
            op_name = operation["op"]
            target = operation.get("target", {})
            params = operation.get("params", {})
            paragraph_index = int(target.get("paragraph_index", -1))
            source_paragraph_index = int(target.get("source_paragraph_index", paragraph_index))
            paragraph = all_paragraphs[source_paragraph_index] if 0 <= source_paragraph_index < len(all_paragraphs) else None

            if op_name == "replace_text":
                if paragraph is None:
                    continue
                old_text = params.get("old_text", "")
                new_text = params.get("new_text", "")
                before = DocxParser.replace_text_in_paragraph(paragraph, old_text, new_text)
                changes.append(
                    self._make_change_record(op_name, paragraph_index, before, paragraph.text, operation.get("reason", ""))
                )

            elif op_name == "rewrite_paragraph":
                if paragraph is None:
                    continue
                rewrite_instruction = params.get("rewrite_instruction", "Please rewrite this paragraph.")
                before = paragraph.text
                rewritten_text = await llm_service.rewrite_paragraph_text(before, rewrite_instruction)
                DocxParser.rewrite_paragraph(paragraph, rewritten_text)
                changes.append(
                    self._make_change_record(op_name, paragraph_index, before, paragraph.text, operation.get("reason", ""))
                )

            elif op_name == "insert_after":
                if paragraph is None:
                    continue
                insert_text = params.get("text", "").strip()
                if not insert_text:
                    continue
                style_name = params.get("style")
                inserted_paragraph = DocxParser.insert_paragraph_after(paragraph, insert_text, style_name)
                changes.append(
                    self._make_change_record(op_name, paragraph_index + 1, "", inserted_paragraph.text, operation.get("reason", ""))
                )

            elif op_name == "heading_promote":
                if paragraph is None:
                    continue
                level = int(params.get("level", 1))
                before = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
                DocxParser.promote_heading(paragraph, level)
                after = f"[{paragraph.style.name if paragraph.style else 'Normal'}] {paragraph.text}"
                changes.append(
                    self._make_change_record(op_name, paragraph_index, before, after, operation.get("reason", ""))
                )
            elif op_name == "set_text_style":
                source_indexes = [int(value) for value in target.get("source_paragraph_indexes", [])]
                if not source_indexes and 0 <= source_paragraph_index < len(all_paragraphs):
                    source_indexes = [source_paragraph_index]
                font_name = params.get("font_name", "")
                font_size_pt = params.get("font_size_pt")
                for source_index in source_indexes:
                    if not (0 <= source_index < len(all_paragraphs)):
                        continue
                    target_paragraph = all_paragraphs[source_index]
                    before = f"[{target_paragraph.style.name if target_paragraph.style else 'Normal'}] {target_paragraph.text}"
                    DocxParser.set_paragraph_font(target_paragraph, font_name=font_name, font_size_pt=font_size_pt)
                    after = f"[{target_paragraph.style.name if target_paragraph.style else 'Normal'}] {target_paragraph.text}"
                    changes.append(
                        self._make_change_record(op_name, source_index, before, after, operation.get("reason", ""))
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
        parts = [part.strip() for part in re.split(r"(?<=[\u3002\uff01\uff1f\uff1b;.!?])", text) if part.strip()]
        return parts or [text]

    def _strip_heading_prefix(self, text: str) -> str:
        return re.sub(r"^#{1,6}\s+", "", text).strip()

    def _strip_list_prefix(self, text: str) -> str:
        return re.sub(r"^(?:[-*]|\d+\.)\s+", "", text).strip()

    def _is_heading_style(self, style_name: str) -> bool:
        normalized = (style_name or "").strip().lower()
        if not normalized:
            return False
        return any(keyword in normalized for keyword in HEADING_STYLE_KEYWORDS)


document_agent = DocumentAgent()

