"""
填表执行工具（fill_table_execute）—— plan/dry_run/commit 闭环的第二、三步

两种填写形态：
- table_fill（统计表）：TableFillPlan{target, fill_mode, column_map, data?|data_token?}
- cell_fills（表单/交叉表/指定位置）：CellFill[{target: Address, value}]

mode=dry_run：纯确定性校验，不写盘，逐条报告 ok/type_mismatch/ambiguous/not_found/empty_value
mode=commit：先重跑 dry_run 复核，硬错误则拒绝；通过后版本化写入，逐格 before/after diff
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import select

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.core import pending_actions
from app.agent.document_engine import (
    DocSnapshot,
    commit_cell_fills,
    commit_table_fill,
    dry_run_cell_fills,
    dry_run_table_fill,
)
from app.agent.document_engine import data_stash, lifecycle
from app.agent.document_engine.fill import preview_cell_fills, preview_table_fill
from app.agent.document_engine.mapping import CellFill, DryRunReport, TableFillPlan
from app.db.postgres import async_session
from app.models.document import Document

logger = logging.getLogger(__name__)


class FillTableExecuteTool(BaseTool):
    """填表执行工具：dry_run 校验 → commit 写入"""

    @property
    def name(self) -> str:
        return "fill_table_execute"

    @property
    def description(self) -> str:
        return """执行填表映射（先 dry_run 校验，再 commit 写入）。必须先调用 fill_table_plan 获取结构与数据。

参数：
- mode: "dry_run"（校验不写盘）或 "commit"（实际写入）。必须先 dry_run，处理完非 ok 项后再 commit
- template_id: 模板文档ID（首次填写）
- output_doc_id: 已生成的输出文档ID（增量填写；与 template_id 二选一）
- table_fill: 统计表填写（行重复结构）：
  {"target": {"kind":"docx_table","table_index":0} 或 {"kind":"xlsx_sheet","sheet":"Sheet1","header_row":2},
   "fill_mode": "overwrite"|"append",
   "column_map": {"模板表头": "源数据列名"},
   "data_token": "plan返回的令牌" 或 "data": [记录数组]}
- cell_fills: 逐格填写（表单字段/交叉表单元格/指定位置），每项：
  {"target": 地址, "value": 值, "source": "来源说明", "rationale": "理由"}
  地址类型：
  - {"kind":"xlsx_cell","cell":"B5","sheet":"Sheet1"}
  - {"kind":"docx_table_cell","table_index":0,"row":1,"col":1}
  - {"kind":"docx_paragraph","paragraph_index":3,"anchor":"段落前20字","index_scope":"all"}
  - {"kind":"content_control","tag":"contract_no"}（无tag时用 "sdt_index"）

dry_run 报告状态：ok / not_found（地址或列不存在）/ ambiguous（锚点重复）/ empty_value（空值提示）
- 只需处理非 ok 项：修正后重新 dry_run 或直接 commit（commit 会再复核一次）
- 表头/映射的列级问题不会阻止 commit（该列自动匹配或填空）；目标不存在/歧义会拒绝写入"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["dry_run", "commit"],
                         "description": "dry_run=校验不写盘；commit=实际写入"},
                "confirm_action_id": {"type": "string",
                                      "description": "（commit 时）dry_run 返回的 action_id。传入后无需重复 template_id/映射参数，自动恢复 dry_run 时暂存的完整提交参数"},
                "template_id": {"type": "string", "description": "模板文档ID（首次填写）"},
                "output_doc_id": {"type": "string", "description": "输出文档ID（增量填写）"},
                "table_fill": {
                    "type": "object",
                    "description": "统计表填写计划（TableFillPlan）",
                },
                "cell_fills": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "逐格填写列表（CellFill[]）",
                },
            },
            "required": ["mode"],
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        mode = params.get("mode")

        # 0. 确认提交：从 pending action 恢复 dry_run 时暂存的完整参数
        #    （LLM 只需传 confirm_action_id，无需跨 run 复制映射/data_token）
        confirm_action_id = params.get("confirm_action_id")
        if mode == "commit" and confirm_action_id:
            entry = pending_actions.get(confirm_action_id)
            if not entry:
                return ToolResult(
                    success=False,
                    error=f"待确认操作不存在或已过期: {confirm_action_id}，请重新走 dry_run 流程"
                )
            if entry["status"] != "pending":
                return ToolResult(
                    success=False,
                    error=f"该操作已被{ '确认' if entry['status'] == 'confirmed' else '取消' }，请勿重复提交"
                )
            stashed = dict(entry["params"])
            stashed["mode"] = "commit"
            params = stashed
            pending_actions.resolve(confirm_action_id, "confirmed")

        # 人工确认模式硬约束：commit 必须走 confirm_action_id 通道（用户点击确认后由服务端发起），
        # 禁止 LLM 自行携带完整参数直接 commit 绕过人工确认
        if mode == "commit" and not confirm_action_id and context.metadata.get("auto_review") is False:
            logger.warning(
                f"[fill_table_execute] 拒绝 LLM 裸 commit（人工确认模式）| "
                f"conv={context.metadata.get('conversation_id')}"
            )
            return ToolResult(
                success=False,
                error="人工确认模式已开启：禁止直接 commit。dry_run 后请结束本轮回复，"
                      "等待用户点击确认卡片；确认后由服务端按暂存参数自动执行写入，无需你再次调用。"
            )

        template_id = params.get("template_id") or ""
        output_doc_id = params.get("output_doc_id") or ""

        if not template_id and not output_doc_id:
            return ToolResult(success=False, error="必须提供 template_id（首次填写）或 output_doc_id（增量填写）")
        for field, value in (("template_id", template_id), ("output_doc_id", output_doc_id)):
            if value:
                uuid_error = BaseTool.validate_uuid(value, field)
                if uuid_error:
                    return ToolResult(success=False, error=uuid_error)

        # 1. 解析映射
        parsed = self._parse_mappings(params)
        if isinstance(parsed, ToolResult):
            return parsed
        table_plan, cell_fills = parsed
        if not table_plan and not cell_fills:
            return ToolResult(success=False, error="table_fill 和 cell_fills 至少提供一个")

        # 2. table_fill 数据装配（data_token 优先于内联 data）
        stash_meta: Dict[str, Any] = {}
        if table_plan and not table_plan.data:
            records_or_error = self._resolve_records(table_plan, params)
            if isinstance(records_or_error, ToolResult):
                return records_or_error
            table_plan.data, stash_meta = records_or_error

        try:
            # 3. 定位校验用文件（dry_run 与 commit 复核都针对当前文件）
            check_doc_id = output_doc_id or template_id
            doc_info = await lifecycle.get_doc_info(check_doc_id)
            if not doc_info:
                return ToolResult(success=False, error=f"文档不存在: {check_doc_id}")
            if doc_info["file_type"] not in ("docx", "xlsx"):
                return ToolResult(success=False, error=f"填表仅支持 docx/xlsx，当前: {doc_info['file_type']}")

            with DocSnapshot.open(doc_info["file_path"], doc_info["file_type"]) as snapshot:
                report = self._dry_run(snapshot, table_plan, cell_fills)
                preview = self._build_preview(snapshot, table_plan, cell_fills)

            # 4. dry_run 模式：返回报告
            if mode == "dry_run":
                return self._dry_run_result(report, preview, params, context)

            # 5. commit：复核硬错误拒绝
            hard_errors = [i for i in report.problem_items
                           if i.status in ("not_found", "ambiguous")
                           and not i.subject.startswith(("表头「", "映射 "))]
            if hard_errors:
                return ToolResult(
                    success=False,
                    error="存在必须处理的校验错误，请修正后重新 commit",
                    data={"dry_run_report": report.model_dump(), "summary": report.summary()},
                )

            return await self._commit(
                table_plan, cell_fills, report,
                template_id, output_doc_id, doc_info, context,
                stash_meta=stash_meta,
            )

        except Exception as e:
            logger.exception(f"[FillTableExecute] 失败: {e}")
            return ToolResult(success=False, error=f"填表执行失败: {str(e)}")

    # ──────────────────────────── 溯源 manifest ────────────────────────────

    async def _persist_provenance(
        self,
        target_doc_id: str,
        table_plan: Optional[TableFillPlan],
        cell_fills: List[CellFill],
        changes: List[Dict[str, Any]],
        template_id: str,
        template_doc,
        stash_meta: Dict[str, Any],
        context: ToolContext,
    ) -> List[str]:
        """把本次填写的溯源信息追加到输出版本 metadata_info["provenance"]["fills"]。

        Returns:
            源文档 ID 列表（供 TemplateUsageEvent.source_file_ids 落库）
        """
        from datetime import datetime
        from uuid import UUID

        from app.agent.document_engine.provenance import get_source

        # 源文档清单：stash meta 优先（取数时已确认），内联 data 兜底为会话选中文档
        via = stash_meta.get("via") or ("inline" if table_plan and table_plan.data else None)
        source_doc_ids: List[str] = [str(d) for d in (stash_meta.get("doc_ids") or [])]
        if not source_doc_ids and table_plan is not None:
            source_doc_ids = [str(d) for d in (context.file_ids or [])] if context else []
            if source_doc_ids and not via:
                via = "inline"

        doc_names: Dict[str, str] = {}
        if source_doc_ids:
            try:
                uuids = [UUID(d) for d in source_doc_ids]
            except ValueError:
                uuids = []
            if uuids:
                async with async_session() as db:
                    result = await db.execute(
                        select(Document.id, Document.original_filename).where(Document.id.in_(uuids))
                    )
                    doc_names = {str(r[0]): r[1] for r in result.fetchall()}

        source_documents = [
            {"doc_id": d, "doc_name": doc_names.get(d, d), "via": via}
            for d in source_doc_ids
        ]

        # 行级来源：commit 时由引擎随 changes 产出（已压缩为区间）
        row_sources = [
            {"target": c.get("target"), "fill_mode": c.get("fill_mode"),
             "filled_rows": c.get("filled_rows"), **(c.get("row_sources") or {})}
            for c in changes if c.get("op") == "table_fill"
        ]
        # 逐格来源：CellFill 声明的 source/rationale
        cell_sources = [
            {"target": c.get("target"), "after": c.get("after"),
             "source": c.get("source"), "rationale": c.get("rationale")}
            for c in changes if c.get("op") == "set_cell"
        ]
        # 防御统计：行数据中实际带溯源标签的行数
        tagged_rows = 0
        if table_plan:
            tagged_rows = sum(1 for r in table_plan.data if get_source(r))

        entry: Dict[str, Any] = {
            "at": datetime.utcnow().isoformat(),
            "run_id": context.metadata.get("run_id") if context else None,
            "conversation_id": context.metadata.get("conversation_id") if context else None,
            "template": (
                {"id": template_id,
                 "name": template_doc.original_filename if template_doc else template_id}
                if template_id else None
            ),
            "via": via,
            "query": stash_meta.get("query") or None,
            "sql": stash_meta.get("sql") or None,
            "source_documents": source_documents,
            "column_map": table_plan.column_map if table_plan else None,
            "row_sources": row_sources,
            "cell_sources": cell_sources,
            "filled_rows": sum(c.get("filled_rows", 0) for c in changes),
            "tagged_rows": tagged_rows,
        }

        try:
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == UUID(str(target_doc_id)))
                )
                doc = result.scalar_one_or_none()
                if doc:
                    info = dict(doc.metadata_info or {})
                    provenance = dict(info.get("provenance") or {})
                    fills = list(provenance.get("fills") or [])
                    fills.append(entry)
                    provenance["fills"] = fills
                    info["provenance"] = provenance
                    doc.metadata_info = info
                    await db.commit()
        except Exception as e:
            # 溯源落库失败不影响填写主流程（数据已写入文件）
            logger.warning(f"[FillTableExecute] 溯源 manifest 落库失败（不影响填写结果）: {e}")

        return source_doc_ids

    # ──────────────────────────── 内部 ────────────────────────────

    def _parse_mappings(self, params: Dict[str, Any]):
        """解析并校验 LLM 的映射参数。返回 (table_plan, cell_fills) 或错误 ToolResult"""
        table_plan: Optional[TableFillPlan] = None
        cell_fills: List[CellFill] = []

        raw_table = params.get("table_fill")
        if raw_table:
            raw_table = dict(raw_table)
            if isinstance(raw_table.get("target"), dict):
                raw_table["target"] = self._infer_target_kind(raw_table["target"])
            try:
                table_plan = TableFillPlan.model_validate(raw_table)
            except ValidationError as e:
                return ToolResult(success=False,
                                  error=f"table_fill 参数格式错误: {e.errors()[0]['msg']}（{e.errors()[0]['loc']}）")

        for raw_cell in params.get("cell_fills") or []:
            raw_cell = dict(raw_cell)
            if isinstance(raw_cell.get("target"), dict):
                raw_cell["target"] = self._infer_target_kind(raw_cell["target"])
            try:
                cell_fills.append(CellFill.model_validate(raw_cell))
            except ValidationError as e:
                return ToolResult(success=False,
                                  error=f"cell_fills 项格式错误: {e.errors()[0]['msg']}（{e.errors()[0]['loc']}）")

        return table_plan, cell_fills

    @staticmethod
    def _infer_target_kind(target: Dict[str, Any]) -> Dict[str, Any]:
        """LLM 常省略 kind 判别字段，按键名推断地址类型"""
        if target.get("kind"):
            return target
        target = dict(target)
        if "table_index" in target and "row" in target:
            target["kind"] = "docx_table_cell"
        elif "table_index" in target:
            target["kind"] = "docx_table"
        elif "cell" in target:
            target["kind"] = "xlsx_cell"
        elif "paragraph_index" in target or "anchor" in target:
            target["kind"] = "docx_paragraph"
        elif "tag" in target or "sdt_index" in target:
            target["kind"] = "content_control"
        elif "sheet" in target or "header_row" in target:
            target["kind"] = "xlsx_sheet"
        return target

    @staticmethod
    def _resolve_records(table_plan: TableFillPlan, params: Dict[str, Any]):
        """从 data_token 取暂存数据。返回 (records, stash_meta) 或错误 ToolResult。

        stash_meta 携带取数口径（doc_ids/query/sql/via），commit 时写入溯源 manifest。
        """
        token = (params.get("table_fill") or {}).get("data_token")
        if not token:
            return ToolResult(
                success=False,
                error="table_fill 缺少数据：请传 data_token（fill_table_plan 返回）或内联 data 数组"
            )
        entry = data_stash.get(token)
        if not entry:
            return ToolResult(
                success=False,
                error=f"data_token 已过期或不存在: {token}，请重新调用 fill_table_plan"
            )
        return entry["records"], (entry.get("meta") or {})

    @staticmethod
    def _dry_run(snapshot: DocSnapshot,
                 table_plan: Optional[TableFillPlan],
                 cell_fills: List[CellFill]) -> DryRunReport:
        report = DryRunReport()
        if table_plan:
            sub = dry_run_table_fill(snapshot, table_plan)
            for item in sub.items:
                report.add(item.subject, item.status, item.detail)
        if cell_fills:
            sub = dry_run_cell_fills(snapshot, cell_fills)
            for item in sub.items:
                report.add(item.subject, item.status, item.detail)
        return report

    @staticmethod
    def _build_preview(snapshot: DocSnapshot,
                       table_plan: Optional[TableFillPlan],
                       cell_fills: List[CellFill]) -> Dict[str, Any]:
        """物化预览数据（不写盘）：统计表给表头+前10行实际将写入的值；逐格给 before→after"""
        preview: Dict[str, Any] = {}
        try:
            if table_plan and table_plan.data:
                preview["table"] = preview_table_fill(snapshot, table_plan)
            if cell_fills:
                preview["cells"] = preview_cell_fills(snapshot, cell_fills)
        except Exception as e:
            logger.warning(f"[FillTableExecute] 预览生成失败（不影响校验）: {e}")
        return preview

    @staticmethod
    def _dry_run_result(report: DryRunReport, preview: Dict[str, Any],
                        params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """dry_run 返回。人工确认模式（auto_review=False）时暂存参数并发确认事件"""
        auto_review = context.metadata.get("auto_review", True)
        # preview 是给用户的 UI 数据，放 metadata（LLM 不可见，节省对话上下文）
        metadata: Dict[str, Any] = {"stage": "dry_run", "preview": preview}
        action_id = None

        if not auto_review:
            # 暂存完整提交参数：确认时 LLM 只需传 confirm_action_id
            action_id = pending_actions.put(
                tool="fill_table_execute",
                params={
                    "template_id": params.get("template_id"),
                    "output_doc_id": params.get("output_doc_id"),
                    "table_fill": params.get("table_fill"),
                    "cell_fills": params.get("cell_fills"),
                },
                summary=report.summary(),
                conversation_id=context.metadata.get("conversation_id"),
            )
            metadata["requires_confirmation"] = True
            metadata["action_id"] = action_id

        return ToolResult(
            success=True,
            data={
                "summary": report.summary(),
                "dry_run_report": report.model_dump(),
                **({"action_id": action_id} if action_id else {}),
                "next_step": (
                    "等待用户确认即可：服务端将按暂存参数直接执行写入，你无需任何后续调用"
                    if not auto_review else
                    ("全部校验通过，请以相同参数调用本工具 mode=commit" if report.all_ok
                     else "请处理上述非 ok 项（修正映射后重新 dry_run 或直接 commit）")
                ),
            },
            metadata=metadata,
        )

    async def _commit(self, table_plan, cell_fills, report: DryRunReport,
                      template_id: str, output_doc_id: str,
                      doc_info: Dict[str, Any], context: ToolContext,
                      stash_meta: Optional[Dict[str, Any]] = None) -> ToolResult:
        """版本化写入：新建输出 v1 或同 run 原地改/新 run version+1"""
        # 解析写入目标（版本化）
        if output_doc_id:
            target_path, _, target_doc_id, is_new_version = await lifecycle.resolve_edit_target(
                doc_info, None, context, origin_type="fill"
            )
            template_doc = None
            if template_id:
                async with async_session() as db:
                    result = await db.execute(select(Document).where(Document.id == template_id))
                    template_doc = result.scalar_one_or_none()
        else:
            async with async_session() as db:
                result = await db.execute(select(Document).where(Document.id == template_id))
                template_doc = result.scalar_one_or_none()
            if not template_doc:
                return ToolResult(success=False, error=f"模板文档不存在: {template_id}")

            from app.services import document_versioning
            async with async_session() as db:
                output_doc = await document_versioning.create_root_output(
                    db,
                    user_id=context.user_id or template_doc.user_id,
                    file_type=template_doc.file_type,
                    origin_type="fill",
                    source_doc=template_doc,
                    run_id=context.metadata.get("run_id"),
                    conversation_id=context.metadata.get("conversation_id"),
                )
                await db.commit()
            target_path = output_doc.file_path
            target_doc_id = str(output_doc.id)
            is_new_version = True

        # 在目标文件上应用映射。重活（打开/写入/保存 workbook）放到线程里执行，
        # 避免病态模板（数万行/数万合并区域）的同步计算阻塞事件循环、拖死整个后端
        def _apply_changes() -> List[Dict[str, Any]]:
            with DocSnapshot.open(target_path, doc_info["file_type"]) as snapshot:
                applied: List[Dict[str, Any]] = []
                if table_plan:
                    table_changes, _ = commit_table_fill(snapshot, table_plan)
                    applied.extend(table_changes)
                if cell_fills:
                    cell_changes, _ = commit_cell_fills(snapshot, cell_fills)
                    applied.extend(cell_changes)
                snapshot.save()
            return applied

        changes = await asyncio.to_thread(_apply_changes)

        reg = await lifecycle.finish_edit(target_doc_id, context)

        # 溯源 manifest：把本次填写的取数口径与行/格级来源写入输出版本的 metadata_info
        # （新版本复制父版本 metadata_info，历史天然随版本链累积）
        source_doc_ids = await self._persist_provenance(
            target_doc_id, table_plan, cell_fills, changes,
            template_id, template_doc, stash_meta or {}, context,
        )

        # 记录模板使用事件
        if template_id:
            async with async_session() as db:
                template_name = template_doc.original_filename if template_doc else template_id
                await lifecycle.record_template_usage(
                    db,
                    template_id=template_id,
                    template_name=template_name,
                    output_file_id=target_doc_id,
                    context=context,
                    source_file_ids=source_doc_ids,
                )

        filled_rows = sum(c.get("filled_rows", 0) for c in changes)
        logger.info(f"[FillTableExecute] commit 完成: {filled_rows} 行 + "
                    f"{sum(1 for c in changes if c.get('op') == 'set_cell')} 格 → {target_path}")

        return ToolResult(
            success=True,
            data={
                "message": f"填写完成：{filled_rows} 行数据"
                           + (f"，{sum(1 for c in changes if c.get('op') == 'set_cell')} 个单元格" if cell_fills else ""),
                "filled_rows": filled_rows,
                "changes": changes[:50],
                "dry_run_summary": report.summary(),
                **reg,
            },
            metadata={
                "template_id": template_id,
                "is_new_version": is_new_version,
            },
        )
