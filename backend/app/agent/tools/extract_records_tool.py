"""
结构化记录提取工具（extract_records）

解决 docx/md/txt 源文档的数据搬运问题：
- 旧路径：LLM 读全文 → 把记录逐字转录成 data 数组（慢、贵、数据常驻对话上下文）
- 新路径：本工具在服务端分块调用 LLM 提取记录 → 暂存 data_stash → 只返回 data_token + 摘要
  记录数据从不进入 Agent 对话上下文

与 source_query 互补：source_query 管 xlsx 源，本工具管 docx/md/txt 源。
"""

import json
import logging
import re
from typing import Any, Dict, List

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.document_engine import data_stash, lifecycle
from app.agent.document_engine.provenance import RESERVED_KEYS, SOURCE_KEY, strip_record, tag_record

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 8000    # 每个提取块的最大字符数
_CHUNK_OVERLAP = 400   # 块间重叠，降低记录被切块边界的概率


class ExtractRecordsTool(BaseTool):
    """从非结构化文档提取结构化记录（服务端执行，数据不入对话上下文）"""

    @property
    def name(self) -> str:
        return "extract_records"

    @property
    def description(self) -> str:
        return """从 docx/md/txt 源文档中提取结构化记录（如统计表的数据行），结果暂存服务端，返回 data_token。

使用场景：填表/填表单时，源文档是 docx/md/txt。
- 禁止把记录逐字转录到 data 参数（慢且浪费上下文）——用本工具提取后凭 data_token 流转
- xlsx 源文档不要用本工具（用 fill_table_plan 的 source_query 自动模式）

参数：
- doc_id: 源文档ID
- columns: 目标列名列表（用模板表头，如 ["城市名","GDP总量（亿元）"]）
- hint: 提取提示（可选，如"每个城市一条记录，GDP 取数值部分"）

返回：data_token（30分钟有效）、total_records、columns、sample（前5行样本）
- 请检查 sample 与 total_records 是否符合预期（如应 100 行却只有 60 行，可用 hint 补充说明后重试）
- 后续：fill_table_plan(template_id=..., data_token=...) → fill_table_execute"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "源文档ID（docx/md/txt）"},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "目标列名列表（用模板表头）",
                },
                "hint": {"type": "string", "description": "提取提示（可选）"},
            },
            "required": ["doc_id", "columns"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        doc_id = params.get("doc_id", "")
        columns = params.get("columns") or []
        hint = params.get("hint", "")

        uuid_error = BaseTool.validate_uuid(doc_id, "doc_id")
        if uuid_error:
            return ToolResult(success=False, error=uuid_error)
        if not columns:
            return ToolResult(success=False, error="columns 不能为空（传入模板表头）")

        doc_info = await lifecycle.get_doc_info(doc_id)
        if not doc_info:
            return ToolResult(success=False, error=f"文档不存在: {doc_id}")
        if doc_info["file_type"] not in ("docx", "md", "txt"):
            return ToolResult(
                success=False,
                error=f"extract_records 仅支持 docx/md/txt，当前: {doc_info['file_type']}。"
                      "xlsx 源请用 fill_table_plan 的 source_query 模式",
            )

        try:
            text = self._read_full_text(doc_info["file_path"], doc_info["file_type"])
            if not text.strip():
                return ToolResult(success=False, error="文档内容为空")

            # xlsx 源：预查各 sheet 行数，让 LLM 给每条记录标注 sheet 行号。
            # 行号有两个用途：① 溯源可精确到行；② 分块重叠处的重复提取可按行号精确去重
            # （此前按全字段去重，同一条记录在两个块里被提取成不同写法时去不掉，
            #  曾导致 100 城市提取出 103 条、LLM 花十几轮找重复）
            sheet_row_counts = self._xlsx_sheet_rows(doc_info) if doc_info["file_type"] == "xlsx" else {}

            chunks = self._split_chunks(text)
            anchors = self._chunk_anchors(text, chunks)
            logger.info(f"[ExtractRecords] {doc_info['original_filename']}: "
                        f"{len(text)} 字符 → {len(chunks)} 块")

            records: List[Dict[str, Any]] = []
            failed_chunks = 0
            for i, chunk in enumerate(chunks):
                chunk_records = await self._extract_chunk(
                    chunk, columns, hint, want_row_no=bool(sheet_row_counts)
                )
                if chunk_records is None:
                    failed_chunks += 1
                    logger.warning(f"[ExtractRecords] 块 {i + 1}/{len(chunks)} 提取失败")
                    continue
                # 溯源标签：面向用户的定位信息（detail 直接展示）
                for record in chunk_records:
                    row_no = record.pop("__row_no", None)
                    if isinstance(row_no, (int, float)) and not isinstance(row_no, bool):
                        row_no = int(row_no)
                    else:
                        row_no = None
                    detail = f"第{row_no}行" if row_no else anchors[i]
                    tag_record(record, doc_id=doc_id,
                               doc_name=doc_info["original_filename"],
                               origin="extract_records", detail=detail,
                               meta={"chunk": f"{i + 1}/{len(chunks)}", "row_no": row_no})
                records.extend(chunk_records)
                logger.info(f"[ExtractRecords] 块 {i + 1}/{len(chunks)} 提取 {len(chunk_records)} 条")

            if failed_chunks == len(chunks):
                return ToolResult(success=False, error="全部分块提取失败（LLM 服务异常），请重试")

            records = self._dedupe(records)
            if not records:
                return ToolResult(
                    success=False,
                    error="未提取到任何记录。请检查 columns 是否与文档内容匹配，或用 hint 描述数据位置",
                )

            data_token = data_stash.put(records, meta={
                "source_doc_id": doc_id,
                "source_doc_name": doc_info["original_filename"],
                "doc_ids": [doc_id],
                "via": "extract_records",
                "columns": columns,
                "hint": hint,
            })

            return ToolResult(
                success=True,
                data={
                    "data_token": data_token,
                    "total_records": len(records),
                    # 列名与样本均剥离内部保留键（溯源标签/行号辅助，不是数据列）
                    "columns": [c for c in records[0].keys() if c not in RESERVED_KEYS],
                    "sample": [strip_record(r) for r in records[:5]],
                    "source_doc": doc_info["original_filename"],
                    "truncated_chunks": failed_chunks,
                    "note": "请核对 total_records 与 sample；数量不符预期时用 hint 补充说明后重试",
                },
            )

        except Exception as e:
            logger.exception(f"[ExtractRecords] 提取失败: {e}")
            return ToolResult(success=False, error=f"记录提取失败: {str(e)}")

    # ──────────────────────────── 内部 ────────────────────────────

    @staticmethod
    def _read_full_text(file_path: str, file_type: str) -> str:
        if file_type == "docx":
            from app.services.document_processor import DocxParser
            return DocxParser().parse(file_path).get("full_text", "")
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _split_chunks(text: str) -> List[str]:
        """按字符数分块（带重叠），尽量在段落边界断开

        步进必须用实际块长（end - start）而非 _CHUNK_CHARS：尾部按换行截短时，
        固定步进会让重叠区超过 _CHUNK_OVERLAP，块边界段落被完整重复进两块，
        造成重复提取（曾导致 100 城市提取出 103 条）。
        """
        if len(text) <= _CHUNK_CHARS:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + _CHUNK_CHARS, len(text))
            if end < len(text):
                # 优先在换行处断开
                newline = text.rfind("\n", start + _CHUNK_CHARS // 2, end)
                if newline > start:
                    end = newline
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = max(end - _CHUNK_OVERLAP, start + 1)
        return chunks

    @staticmethod
    def _xlsx_sheet_rows(doc_info: Dict[str, Any]) -> Dict[str, int]:
        """xlsx 各 sheet 的最大行号（预查，用于行号标注与按行号去重）；失败返回 {}"""
        try:
            from openpyxl import load_workbook
            wb = load_workbook(doc_info["file_path"], read_only=True, data_only=True)
            counts = {name: (wb[name].max_row or 0) for name in wb.sheetnames}
            wb.close()
            return counts
        except Exception as e:
            logger.warning(f"[ExtractRecords] 预查 sheet 行数失败（按无行号模式提取）: {e}")
            return {}

    @staticmethod
    def _chunk_anchors(text: str, chunks: List[str]) -> List[str]:
        """每个块在原文中的起始位置 → 开头摘录（溯源定位用，用户可直接搜回原文）

        块由 _split_chunks 按顺序生成（重叠只发生在前一块尾部），
        从上一位置起 find 块头 32 字即可唯一锚定。
        """
        anchors: List[str] = []
        pos = 0
        for chunk in chunks:
            probe = chunk[:32]
            idx = text.find(probe, pos)
            if idx < 0:
                idx = pos  # 防御：找不到时按上一位置续（不会发生）
            # 取块开头第一个非空行的前 30 字作为摘录
            first_line = ""
            for line in chunk.splitlines():
                if line.strip():
                    first_line = line.strip()
                    break
            snippet = first_line[:30]
            if len(first_line) > 30:
                snippet += "…"
            anchors.append(f"原文约第{idx + 1}字起：「{snippet}」")
            pos = idx + max(len(chunk) - _CHUNK_OVERLAP, 1)
        return anchors

    @staticmethod
    async def _extract_chunk(chunk: str, columns: List[str], hint: str,
                             want_row_no: bool = False) -> List[Dict[str, Any]] | None:
        """对单个块调用 LLM 提取记录；失败返回 None

        want_row_no（xlsx 源）：要求 LLM 额外输出 __row_no（记录所在 sheet 行号），
        用于精确溯源与分块重叠处的按行号去重。
        """
        from app.services.llm_service import llm_service

        row_no_clause = (
            "- 每条记录额外加一个键 __row_no，值为该条数据在表格中的行号（整数，表头为第1行，数据从第2行起）\n"
            if want_row_no else ""
        )
        prompt = f"""请从以下文档片段中提取结构化数据记录。

目标列：{json.dumps(columns, ensure_ascii=False)}
{f"提取提示：{hint}" if hint else ""}

要求：
- 每条记录是一个 JSON 对象，键严格使用上述列名
{row_no_clause}- 数值列提取为数字（去掉千分位逗号；带"修正值"等注释的只取数值部分；带单位的去掉单位）
- 只提取片段中明确出现的数据，禁止编造；某列确实没有则给 null
- 片段开头/结尾可能是残句（分块重叠所致），跳过信息不全的记录
- 只返回 JSON 数组，不要任何其他内容

文档片段：
{chunk}"""

        try:
            response = await llm_service.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                enable_thinking=False,
            )
            text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
            match = re.search(r'\[[\s\S]*\]', text)
            if not match:
                return []
            records = json.loads(match.group())
            if not isinstance(records, list):
                return []
            # 只保留字典项，且键收敛到目标列
            cleaned = []
            for item in records:
                if isinstance(item, dict):
                    cleaned.append({col: item.get(col) for col in columns})
            return cleaned
        except Exception as e:
            logger.warning(f"[ExtractRecords] 块提取异常: {e}")
            return None

    @staticmethod
    def _dedupe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重（重叠块会产生重复记录）。

        两级策略：
        1. xlsx 源且带 sheet 行号的记录按行号去重——同一条数据在两个块里被提取成
           不同写法（如 "4,925.30" vs 4925.3）时，全字段比对去不掉，行号能精确命中；
           保留首见（首块记录完整度更高，重叠区在块尾）
        2. 其余记录按全字段去重（溯源标签等内部保留键不参与比对）
        """
        seen_rows = set()
        seen_keys = set()
        unique = []
        for record in records:
            src = record.get(SOURCE_KEY) or {}
            row_no = (src.get("meta") or {}).get("row_no")
            if row_no is not None:
                if row_no in seen_rows:
                    continue
                seen_rows.add(row_no)
            else:
                key = tuple(sorted((k, str(v)) for k, v in record.items()
                                   if k not in RESERVED_KEYS))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            unique.append(record)
        return unique
