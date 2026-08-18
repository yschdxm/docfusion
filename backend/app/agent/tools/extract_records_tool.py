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

            chunks = self._split_chunks(text)
            logger.info(f"[ExtractRecords] {doc_info['original_filename']}: "
                        f"{len(text)} 字符 → {len(chunks)} 块")

            records: List[Dict[str, Any]] = []
            failed_chunks = 0
            for i, chunk in enumerate(chunks):
                chunk_records = await self._extract_chunk(chunk, columns, hint)
                if chunk_records is None:
                    failed_chunks += 1
                    logger.warning(f"[ExtractRecords] 块 {i + 1}/{len(chunks)} 提取失败")
                    continue
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
                "columns": columns,
                "hint": hint,
            })

            return ToolResult(
                success=True,
                data={
                    "data_token": data_token,
                    "total_records": len(records),
                    "columns": list(records[0].keys()),
                    "sample": records[:5],
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
        """按字符数分块（带重叠），尽量在段落边界断开"""
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
            start = max(end - _CHUNK_OVERLAP, start + 1) if end < len(text) else len(text)
        return chunks

    @staticmethod
    async def _extract_chunk(chunk: str, columns: List[str], hint: str) -> List[Dict[str, Any]] | None:
        """对单个块调用 LLM 提取记录；失败返回 None"""
        from app.services.llm_service import llm_service

        prompt = f"""请从以下文档片段中提取结构化数据记录。

目标列：{json.dumps(columns, ensure_ascii=False)}
{f"提取提示：{hint}" if hint else ""}

要求：
- 每条记录是一个 JSON 对象，键严格使用上述列名
- 数值列提取为数字（去掉千分位逗号；带"修正值"等注释的只取数值部分；带单位的去掉单位）
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
        """按全字段去重（重叠块会产生重复记录）"""
        seen = set()
        unique = []
        for record in records:
            key = tuple(sorted((k, str(v)) for k, v in record.items()))
            if key not in seen:
                seen.add(key)
                unique.append(record)
        return unique
