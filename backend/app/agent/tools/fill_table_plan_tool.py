"""
填表计划工具（fill_table_plan）—— plan/dry_run/commit 闭环的第一步

职责（只读，不写任何文件）：
1. 分析模板结构（复用 analyze_template，含统计表/表单/交叉表分类）
2. 获取源数据（source_query 自动查询 或 data 直传），暂存并返回 data_token
3. 生成数据摘要 + 建议列映射（suggested_column_map，供 LLM 审核修正）

LLM 拿到本工具的返回后，产出最终映射（column_map / cell_fills），
再调用 fill_table_execute 先 dry_run 校验、后 commit 写入。
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.document_engine import data_stash
from app.agent.document_engine.datasource import build_data_summary, fetch_all_data
from app.agent.document_engine.headers import get_template_headers
from app.agent.document_engine.provenance import data_columns_of, tag_record
from app.agent.tools.get_template_structure_tool import analyze_template
from app.db.postgres import async_session
from app.models.document import Document

logger = logging.getLogger(__name__)


class FillTablePlanTool(BaseTool):
    """填表计划工具：结构 + 数据 + 建议映射，一次备齐"""

    @property
    def name(self) -> str:
        return "fill_table_plan"

    @property
    def description(self) -> str:
        return """准备填表：分析模板结构 + 获取源数据 + 给出建议列映射。只读操作，不修改任何文件。

返回内容：
- structure: 模板结构（同 get_template_structure，含统计表/表单/交叉表分类）
- template_headers: 目标表格的表头
- data_summary: 源数据摘要（列质量统计 + 首尾样本行）
- data_columns: 源数据列名列表
- total_records: 记录总数
- data_token: 数据暂存令牌（30分钟有效），fill_table_execute 凭它取数，不要自己搬运数据
- executed_sql: source_query 模式实际执行的 SQL，用于核对取数口径（重点：过滤条件是否完整、
  有没有不该有的 GROUP BY 聚合），不符时修正 query 重新调用
- suggested_column_map: 建议的列映射（模板表头 → 源数据列名），请审核修正后在 execute 中回传

取数口径铁律：默认返回满足条件的**原始记录行**（用户说"日期 X 到 Y 的数据"= 该范围内每一行），
禁止自行 GROUP BY/聚合；仅当用户明确要求"汇总/统计/每个实体一行"时才聚合，且一次写清分组与每列规则。

后续动作：
1. 审核 suggested_column_map 和数据摘要
2. 生成最终 table_fill（column_map + target）和/或 cell_fills（逐格填写，用于表单/交叉表/指定位置）
3. 调 fill_table_execute(mode=dry_run) 校验 → 处理非 ok 项 → mode=commit 写入"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_id": {"type": "string", "description": "模板文档ID"},
                "source_query": {
                    "type": "object",
                    "properties": {
                        "doc_ids": {"type": "array", "items": {"type": "string"}, "description": "源文档ID列表"},
                        "query": {"type": "string", "description": "自然语言查询描述"},
                        "max_rows": {"type": "integer", "default": 500, "description": "最大查询行数"},
                        "fetch_all": {"type": "boolean", "default": False, "description": "获取全部数据（自动分批）"},
                    },
                    "description": "自动数据源模式（仅限 xlsx 源文档）。与 data 二选一",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "直接传入的记录数组（仅少量记录时用；docx/md/txt 源的大批量提取请先用 extract_records 获取 data_token）",
                },
                "data_token": {
                    "type": "string",
                    "description": "extract_records 返回的数据令牌（大批量记录的首选方式，避免在对话中搬运数据）",
                },
                "target_table_index": {"type": "integer", "description": "（docx）目标表格索引。不传则返回所有表格结构供选择"},
                "sheet_name": {"type": "string", "description": "（xlsx）目标工作表。不传则返回所有工作表结构供选择"},
                "header_row": {"type": "integer", "description": "（xlsx）表头行号（1-based），缺省自动探测"},
            },
            "required": ["template_id"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        template_id = params.get("template_id", "")
        uuid_error = BaseTool.validate_uuid(template_id, "template_id")
        if uuid_error:
            return ToolResult(success=False, error=uuid_error)

        source_query = params.get("source_query")
        inline_data = params.get("data") or []
        data_token = params.get("data_token")
        target_table_index = params.get("target_table_index")
        sheet_name = params.get("sheet_name")
        header_row = params.get("header_row")

        try:
            # 1. 模板文档与结构
            async with async_session() as db:
                result = await db.execute(select(Document).where(Document.id == template_id))
                template_doc = result.scalar_one_or_none()
            if not template_doc:
                return ToolResult(success=False, error=f"模板文档不存在: {template_id}")

            analysis = await analyze_template(template_doc)

            # 2. 目标表头（目标明确时；不明确则由 structure 供 LLM 选择）
            template_headers: List[str] = []
            target_resolved = (target_table_index is not None) or bool(sheet_name) \
                or template_doc.file_type == "xlsx"
            if target_resolved:
                try:
                    template_headers = get_template_headers(
                        template_doc.file_path, template_doc.file_type,
                        target_table_index, sheet_name=sheet_name, header_row=header_row,
                    )
                except ValueError as e:
                    return ToolResult(success=False, error=str(e))

            # 3. 源数据
            records: List[Dict[str, Any]] = []
            executed_sql = ""
            source_doc_ids: List[str] = []
            if data_token:
                # extract_records 等工具暂存的数据：直接沿用原 token（不重复暂存）
                entry = data_stash.get(data_token)
                if not entry:
                    return ToolResult(
                        success=False,
                        error=f"data_token 已过期或不存在: {data_token}，请重新提取数据"
                    )
                records = entry["records"]
                source_doc_ids = (entry.get("meta") or {}).get("doc_ids") or []
            elif source_query and not inline_data:
                records_or_error = await self._fetch_source_records(
                    source_query, template_headers, context
                )
                if isinstance(records_or_error, ToolResult):
                    return records_or_error
                records, executed_sql, source_doc_ids = records_or_error
            elif inline_data:
                records = inline_data
                source_doc_ids = list(context.file_ids or []) if context else []

            response: Dict[str, Any] = {
                "structure": analysis,
                "template_headers": template_headers,
                "target_hint": self._target_hint(template_doc.file_type, analysis,
                                               target_table_index, sheet_name),
            }
            if executed_sql:
                # 实际执行的 SQL：供主 LLM 核对取数口径（聚合/过滤是否符合预期），减少盲目重试
                response["executed_sql"] = executed_sql[:500]

            if records:
                if not data_token:
                    data_token = data_stash.put(records, meta={
                        "template_id": template_id,
                        "query": (source_query or {}).get("query", ""),
                        # 溯源元数据：execute commit 时据此生成 provenance manifest
                        "doc_ids": source_doc_ids,
                        "sql": executed_sql,
                        "via": "sql_query" if source_query else ("inline" if inline_data else "unknown"),
                    })
                response.update({
                    "data_token": data_token,
                    "total_records": len(records),
                    "data_columns": data_columns_of(records),
                    "data_summary": build_data_summary(records, template_headers),
                })
                # 建议列映射（LLM 草稿，供主 LLM 审核修正）
                if template_headers:
                    suggested = await self._suggest_column_map(
                        template_headers, data_columns_of(records)
                    )
                    if suggested:
                        response["suggested_column_map"] = suggested

            return ToolResult(success=True, data=response)

        except Exception as e:
            logger.exception(f"[FillTablePlan] 失败: {e}")
            return ToolResult(success=False, error=f"填表计划失败: {str(e)}")

    async def _fetch_source_records(
        self, source_query: Dict, template_headers: List[str], context: ToolContext
    ):
        """source_query 模式取数（仅限 xlsx 源文档）

        返回 (records, executed_sql, source_doc_ids) 或错误 ToolResult。
        executed_sql 透给主 LLM 核对取数口径（聚合/过滤是否符合预期），减少盲目重试。
        取数后为每条记录打 `_source` 溯源标签（见 provenance.py）。
        """
        sq_doc_ids = source_query.get("doc_ids") or context.file_ids
        sq_query = source_query.get("query", "")
        sq_max_rows = source_query.get("max_rows", 500)
        fetch_all = source_query.get("fetch_all", False)

        if not sq_query:
            return ToolResult(success=False, error="source_query.query 不能为空")
        if not sq_doc_ids:
            return ToolResult(success=False, error="source_query 模式需要 doc_ids 或已选中的源文档")

        # 源文档类型校验（同时取文件名供溯源打标）：自动查询仅适用于 xlsx
        async with async_session() as db:
            result = await db.execute(
                select(Document.id, Document.file_type, Document.original_filename)
                .where(Document.id.in_(sq_doc_ids))
            )
            rows = result.fetchall()
            doc_names = {str(row[0]): (row[2] or str(row[0])) for row in rows}
            non_xlsx = {row[1] for row in rows} - {"xlsx"}
            if non_xlsx:
                return ToolResult(
                    success=False,
                    error=(
                        f"source_query 自动模式仅适用于xlsx源文档，当前包含: {', '.join(non_xlsx)}。"
                        f"对非xlsx文档请先用 read_document / rag_search 提取数据，再通过 data 参数传入。"
                    ),
                )

        from app.services.sql_query_service import sql_query_service as sql_service

        # 防聚合护栏：默认要原始记录行，只有 query 明确要求汇总/统计才允许 GROUP BY
        anti_aggregation = (
            "重要：除非上述需求明确要求汇总/统计/合计，否则必须返回满足条件的原始记录行，"
            "禁止自行 GROUP BY 或聚合函数（SUM/MAX/AVG/COUNT）压缩行数。"
        )

        # 多文档联合查询时让 SQL 携带行级来源表名（用于数据溯源）
        provenance_hint = ""
        if len(sq_doc_ids) > 1:
            provenance_hint = (
                "本次查询涉及多个数据表。请在 SELECT 中额外输出一个常量列 __source_table，"
                "值为每行数据所在表的表名（多表 UNION 时每段各写自己的表名字符串字面量；单表查询直接写该表名）。"
            )

        # 溯源行号：让 SQL 在 SELECT 中带上源表的 __seq 物理序号列（xlsx 入库时生成，= sheet 行号-1）。
        # 直接 SELECT 一列远比要求模型写 ROW_NUMBER 窗口函数可靠——后者常被模型忽略或用错 ORDER BY，
        # 导致筛选查询的行号从 1 重排（"德州/潍坊/临沂所有站点"全显示成"2-N行"）。
        # 只有表里有 __seq 列才提示（存量表没有则退化为文档级溯源，不输出错误行号）。
        has_seq = await self._tables_have_seq(sq_doc_ids)
        row_no_hint = ""
        if has_seq:
            row_no_hint = (
                "请在 SELECT 中原样带上源表的 \"__seq\" 列（它是每条记录在源表中的物理序号，"
                "直接 SELECT 即可，**不要**对它做窗口函数/重命名以外的任何处理，"
                "也**不要**用查询的排序或筛选重新编号）。多表 UNION 时每段各自带上自己的 __seq。"
                "若查询有 GROUP BY 聚合则无法对应单条源记录，此时不要输出 __seq。"
            )

        headers_str = "，".join(template_headers)
        if fetch_all:
            augmented = (
                f"{sq_query}\n\n"
                f"{anti_aggregation}\n"
                f"{provenance_hint}\n"
                f"{row_no_hint}\n"
                f"模板表头（可能与数据库列名有差异）：{headers_str}\n"
                f"请使用 AS 将列名重命名为与模板表头一致。请返回所有匹配的数据，不要限制行数。"
            )
            meta: Dict[str, Any] = {}
            records = await fetch_all_data(sql_service, augmented, sq_doc_ids, out_meta=meta)
            sheet_names = await self._fetch_sheet_names(sq_doc_ids)
            self._tag_records(records, sq_doc_ids, doc_names, sheet_names)
            return records, meta.get("sql", ""), sq_doc_ids

        augmented = (
            f"{sq_query}\n\n"
            f"{anti_aggregation}\n"
            f"{provenance_hint}\n"
            f"{row_no_hint}\n"
            f"模板表头（可能与数据库列名有差异）：{headers_str}\n"
            f"请使用 AS 将列名重命名为与模板表头一致。请确保返回不超过 {sq_max_rows} 行数据。"
        )
        query_result = await sql_service.generate_and_execute(
            question=augmented, doc_ids=sq_doc_ids, max_retries=3
        )
        if query_result.get("error"):
            return ToolResult(success=False, error=f"源数据查询失败: {query_result['error']}")
        records = query_result.get("records", [])
        sheet_names = await self._fetch_sheet_names(sq_doc_ids)
        self._tag_records(records, sq_doc_ids, doc_names, sheet_names)
        return records, query_result.get("sql", ""), sq_doc_ids

    @staticmethod
    async def _tables_have_seq(doc_ids: List[str]) -> bool:
        """源文档的 PG 表是否都有 __seq 物理序号列（决定能否做行级溯源）"""
        patterns = [f"{str(did)[:8]}%" for did in doc_ids if len(str(did)) >= 8]
        if not patterns:
            return False
        from sqlalchemy import text as sa_text
        try:
            async with async_session() as db:
                for pattern in patterns:
                    result = await db.execute(sa_text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name LIKE :p"
                    ), {"p": pattern})
                    for (table_name,) in result.fetchall():
                        col_result = await db.execute(sa_text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema='public' AND table_name=:t AND column_name='__seq'"
                        ), {"t": table_name})
                        if not col_result.fetchone():
                            return False
            return True
        except Exception as e:
            logger.warning(f"[FillTablePlan] 检查 __seq 列失败（退化为无行号）: {e}")
            return False

    @staticmethod
    async def _fetch_sheet_names(doc_ids: List[str]) -> Dict[str, str]:
        """数据表名 → sheet 名（表名 = {doc_id前8位}_{sheet名}，sheet 名可能含下划线）

        多文档表名前缀可能相同（doc_id 前8位撞车）时，长前缀优先匹配。
        查询失败返回 {}（溯源退化为只到文档级）。
        """
        if not doc_ids:
            return {}
        patterns = [f"{str(did)[:8]}%" for did in doc_ids if len(str(did)) >= 8]
        if not patterns:
            return {}
        from sqlalchemy import text as sa_text
        mapping: Dict[str, str] = {}
        try:
            async with async_session() as db:
                for pattern in patterns:
                    result = await db.execute(sa_text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name LIKE :p"
                    ), {"p": pattern})
                    for (table_name,) in result.fetchall():
                        # sheet 名 = 表名去掉 {doc_id前8位}_ 前缀
                        prefix_len = pattern.index("%")  # 8
                        sheet = table_name[prefix_len + 1:] if len(table_name) > prefix_len else table_name
                        mapping[table_name] = sheet
        except Exception as e:
            logger.warning(f"[FillTablePlan] 查询数据表 sheet 映射失败（溯源退化为文档级）: {e}")
        return mapping

    @staticmethod
    def _tag_records(records: List[Dict[str, Any]], doc_ids: List[str],
                     doc_names: Dict[str, str],
                     sheet_names: Optional[Dict[str, str]] = None) -> None:
        """为 SQL 取数结果打行级溯源标签（原地修改）

        - 单文档：全部记录直接归属该文档；有 __seq/__row_no 时 detail=「第N行」
        - 多文档：读取 SQL 服务按提示输出的 __source_table 列，按表名前缀（doc_id 前8位）
          反查所属文档；该列缺失/无法反查时标记为"多文档混合查询"，标签降级但不丢数据
        - 行号取 __seq（物理序号，= sheet 行号-1，模型直接 SELECT），兼容旧 __row_no；
          sheet 第2行=表第1行，故 sheet 行号=行号+1
        """
        sheet_names = sheet_names or {}
        prefix_map = {str(did)[:8]: (str(did), doc_names.get(str(did), str(did))) for did in doc_ids}

        for record in records:
            table_name = record.pop("__source_table", None)
            # 行号优先取 __seq（物理序号，= sheet 行号-1），兼容旧提示的 __row_no。
            # __seq 是模型直接 SELECT 的列；__row_no 是早期窗口函数方案（保留向后兼容）。
            row_no = record.pop("__seq", None)
            if row_no is None:
                row_no = record.pop("__row_no", None)
            sheet_row = None
            if isinstance(row_no, (int, float)) and not isinstance(row_no, bool):
                sheet_row = int(row_no) + 1  # 表第1行 = sheet 第2行（表头占第1行）

            matched = None
            if table_name:
                matched = prefix_map.get(str(table_name)[:8])

            if matched:
                doc_id, doc_name = matched
                sheet = sheet_names.get(str(table_name))
                tag_record(
                    record, doc_id=doc_id, doc_name=doc_name, origin="sql_query",
                    detail=_row_detail(sheet, sheet_row, str(table_name)),
                    meta={"row_no": sheet_row, "sheet": sheet, "table": str(table_name) or None},
                )
            elif len(doc_ids) == 1:
                doc_id = str(doc_ids[0])
                doc_name = doc_names.get(doc_id, doc_id)
                tag_record(
                    record, doc_id=doc_id, doc_name=doc_name, origin="sql_query",
                    detail=_row_detail(None, sheet_row, None),
                    meta={"row_no": sheet_row},
                )
            else:
                tag_record(
                    record, doc_id=None, doc_name="多文档混合查询", origin="sql_query",
                    detail=_row_detail(None, sheet_row, "、".join(doc_names.values())),
                    meta={"row_no": sheet_row},
                )


    @staticmethod
    async def _suggest_column_map(template_headers: List[str], source_columns: List[str]) -> Dict[str, str]:
        """建议列映射（复用现有 AI 列映射能力，产出供主 LLM 审核的草稿）"""
        try:
            from app.services.llm_service import llm_service
            mapping = await llm_service.map_columns(template_headers, source_columns)
            return mapping or {}
        except Exception as e:
            logger.warning(f"[FillTablePlan] 建议列映射失败（不影响主流程）: {e}")
            return {}

    @staticmethod
    def _target_hint(file_type: str, analysis: Dict[str, Any],
                     target_table_index: Optional[int], sheet_name: Optional[str]) -> str:
        """目标选择提示：多表格/多工作表时必须由 LLM 显式指定"""
        if file_type == "docx":
            tables = analysis.get("tables") or []
            if target_table_index is not None:
                return f"已指定目标表格 {target_table_index}"
            if len(tables) > 1:
                return (f"文档有 {len(tables)} 个表格，请根据各表格的 context.preceding_text "
                        f"判断用途，在 execute 的 table_fill.target.table_index 中显式指定")
            if len(tables) == 1:
                return "文档有 1 个表格，target.table_index=0"
            return "文档中没有表格"
        sheets = analysis.get("sheets") or []
        if sheet_name:
            return f"已指定工作表 {sheet_name}"
        if len(sheets) > 1:
            names = [s.get("name") for s in sheets]
            return f"工作簿有 {len(sheets)} 个工作表 {names}，请在 target.sheet 中显式指定"
        return "单工作表，target.sheet 可省略"


def _row_detail(sheet: Optional[str], sheet_row: Optional[int],
                fallback: Optional[str]) -> Optional[str]:
    """溯源定位文案：优先 sheet+行号，退而行号，再退源表名/文档"""
    parts = []
    if sheet:
        parts.append(f"工作表[{sheet}]")
    if sheet_row:
        parts.append(f"第{sheet_row}行")
    if parts:
        return " ".join(parts)
    return fallback or None
