"""
表单填写工具 - 填写Word/Excel文档中的表单字段

重构后职责（薄壳编排）：
1. 获取表单字段（analyze_template，含 field_id 与内容控件）
2. 字段匹配（确定性评分，产出映射草稿；LLM 可用 fields 参数精确指定）
3. mode=dry_run：引擎逐字段定位校验，返回报告不写盘
4. mode=commit：版本化写入，逐字段 before/after 回报

定位与写入已收敛到文档引擎层（form_fill.py locator + ops），
本文件不再含任何 docx/openpyxl 直接操作。
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import select

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.core import pending_actions
from app.agent.document_engine import DocSnapshot, lifecycle
from app.agent.document_engine.form_fill import (
    PreparedFill,
    match_data_to_fields,
    prepare_form_field,
    prepare_table_rows_field,
    resolve_field_items,
)
from app.agent.document_engine.mapping import DryRunReport
from app.agent.tools.get_template_structure_tool import analyze_template
from app.db.postgres import async_session
from app.models.document import Document
from app.services import document_versioning

logger = logging.getLogger(__name__)


class FillFormTool(BaseTool):
    """表单填写工具（dry_run/commit 两阶段）"""

    @property
    def name(self) -> str:
        return "fill_form"

    @property
    def description(self) -> str:
        return """填写文档中的表单字段（Word表单和Excel纵向表单），dry_run 校验 + commit 写入两阶段。

前置步骤（必须）：
- 先调用 get_template_structure 获取字段列表（含稳定 field_id），
  然后用 fields 参数按 field_id 精确填写

参数说明：
- mode: "dry_run"（校验不写盘，先调）或 "commit"（实际写入）
- fields（推荐）: 字段数组，每项 {"field_id": "F1", "value": "填写内容"}
  - field_id 来自 get_template_structure 返回的 fields[].field_id
  - 也接受 {"label": "姓名", "value": "张三"} 按标签匹配
- data（兼容模式）: 键值对 {"姓名": "张三"}，按标签自动匹配字段

支持的表单类型：
- Word: 下划线______、方括号【】、冒号模式（姓名：）、表格表单、内容控件（按 tag 定位）
- Excel纵向表单: A列标签B列填值，按 get_template_structure 返回的坐标写入

填写模式：
- overwrite: 覆盖现有内容（首次填写使用）
- append: 追加到已有内容后面（增量填写使用）

增量填写：
- 首次填写传 template_id，返回 output_file_id
- 后续补充传 output_doc_id=上次返回的ID + template_id（用于字段定位）
- 未匹配的字段会在 unmatched_keys 中返回，请检查标签拼写"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["dry_run", "commit"],
                    "default": "dry_run",
                    "description": "dry_run=校验不写盘（先调）；commit=实际写入（dry_run 通过后调）"
                },
                "confirm_action_id": {
                    "type": "string",
                    "description": "（commit 时）dry_run 返回的 action_id。传入后自动恢复 dry_run 时暂存的完整参数，无需重复 fields/data"
                },
                "template_id": {
                    "type": "string",
                    "description": "模板文档ID（首次填写时必需；增量填写时也需提供，用于字段定位）"
                },
                "output_doc_id": {
                    "type": "string",
                    "description": "已生成的输出文档ID（增量填写时提供）"
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_id": {"type": "string", "description": "get_template_structure 返回的字段ID，如 F1"},
                            "label": {"type": "string", "description": "字段标签（未提供field_id时按标签匹配）"},
                            "value": {"description": "填写内容"}
                        }
                    },
                    "description": "要填写的字段数组（推荐）。每项提供 field_id 或 label + value"
                },
                "data": {
                    "type": "object",
                    "description": "兼容模式：填表数据键值对。key为字段标签（如\"姓名\"），value为填写内容",
                    "additionalProperties": True
                },
                "fill_mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "default": "overwrite",
                    "description": "填写模式：overwrite=覆盖现有内容，append=追加到已有内容后面"
                },
                "field_mapping": {
                    "type": "object",
                    "description": "手动字段映射（可选，仅 data 模式），当自动匹配失败时使用",
                    "additionalProperties": True
                }
            },
            "required": []
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            mode = params.get("mode", "dry_run")

            # 0. 确认提交：从 pending action 恢复 dry_run 时暂存的完整参数
            confirm_action_id = params.get("confirm_action_id")
            if mode == "commit" and confirm_action_id:
                entry = pending_actions.get(confirm_action_id)
                if not entry:
                    return ToolResult(
                        success=False,
                        error=f"待确认操作不存在或已过期: {confirm_action_id}，请重新走 dry_run 流程"
                    )
                if entry["status"] != "pending":
                    return ToolResult(success=False, error="该操作已被确认或取消，请勿重复提交")
                stashed = dict(entry["params"])
                stashed["mode"] = "commit"
                params = stashed
                pending_actions.resolve(confirm_action_id, "confirmed")

            # 人工确认模式硬约束：commit 必须走 confirm_action_id 通道（用户点击确认后由服务端发起），
            # 禁止 LLM 自行携带完整参数直接 commit 绕过人工确认
            if mode == "commit" and not confirm_action_id and context.metadata.get("auto_review") is False:
                logger.warning(
                    f"[fill_form] 拒绝 LLM 裸 commit（人工确认模式）| "
                    f"conv={context.metadata.get('conversation_id')}"
                )
                return ToolResult(
                    success=False,
                    error="人工确认模式已开启：禁止直接 commit。dry_run 后请结束本轮回复，"
                          "等待用户点击确认卡片；确认后由服务端按暂存参数自动执行写入，无需你再次调用。"
                )

            template_id = params.get("template_id", "")
            output_doc_id = params.get("output_doc_id", "")
            field_items = params.get("fields") or []
            data = params.get("data") or {}
            fill_mode = params.get("fill_mode", "overwrite")
            field_mapping = params.get("field_mapping", {})

            if not field_items and not data:
                return ToolResult(success=False, error="填写内容不能为空（提供 fields 数组或 data 键值对）")

            for field, value in (("template_id", template_id), ("output_doc_id", output_doc_id)):
                if value:
                    uuid_error = BaseTool.validate_uuid(value, field)
                    if uuid_error:
                        return ToolResult(success=False, error=uuid_error)

            if not template_id and not output_doc_id:
                return ToolResult(success=False, error="首次填写必须提供template_id")

            # 1. 结构分析（优先分析模板，缓存稳定命中；否则分析输出文档自身）
            structure_doc_id = template_id or output_doc_id
            async with async_session() as db:
                result = await db.execute(select(Document).where(Document.id == structure_doc_id))
                structure_doc = result.scalar_one_or_none()
            if not structure_doc:
                return ToolResult(success=False, error=f"结构分析目标文档不存在: {structure_doc_id}")

            analysis = await analyze_template(structure_doc)
            form_fields = analysis.get("fields", [])
            if not form_fields:
                return ToolResult(
                    success=False,
                    error="未检测到可填写的表单字段（structure_type="
                          f"{analysis.get('structure_type')}）。若是数据表格请改用 fill_table_plan"
                )

            # 2. 字段匹配（确定性评分，产出映射）
            if field_items:
                matched_fields, unmatched_keys = resolve_field_items(field_items, form_fields)
            else:
                matched_fields = match_data_to_fields(data, form_fields, field_mapping)
                unmatched_keys = list(set(data.keys()) - {m['data_key'] for m in matched_fields})

            if not matched_fields:
                return ToolResult(
                    success=False,
                    error=f"没有字段匹配成功。unmatched: {unmatched_keys}",
                    data={"unmatched_keys": unmatched_keys},
                )

            # 3. 校验用文件：dry_run 针对当前文件（模板或已有输出）
            check_doc_id = output_doc_id or template_id
            doc_info = await lifecycle.get_doc_info(check_doc_id)
            if not doc_info:
                return ToolResult(success=False, error=f"文档不存在: {check_doc_id}")
            if doc_info["file_type"] not in ("docx", "xlsx"):
                return ToolResult(success=False,
                                  error=f"表单填写支持docx/xlsx格式，当前格式: {doc_info['file_type']}")

            with DocSnapshot.open(doc_info["file_path"], doc_info["file_type"]) as snapshot:
                prepared = self._prepare_all(snapshot, matched_fields, fill_mode)

            report = self._build_report(prepared)

            # 4. dry_run：返回报告
            if mode == "dry_run":
                auto_review = context.metadata.get("auto_review", True)
                # preview 是给用户的 UI 数据，放 metadata（LLM 不可见，节省对话上下文）
                metadata: Dict[str, Any] = {
                    "stage": "dry_run",
                    "preview": {"cells": [
                        {"target": p.subject, "before": p.before, "after": p.after,
                         "status": "ok" if p.ok else p.status}
                        for p in prepared
                    ]},
                }
                action_id = None
                if not auto_review:
                    action_id = pending_actions.put(
                        tool="fill_form",
                        params={
                            "template_id": template_id,
                            "output_doc_id": output_doc_id,
                            "fields": field_items,
                            "data": data,
                            "fill_mode": fill_mode,
                            "field_mapping": field_mapping,
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
                        "matched_fields": len(matched_fields),
                        "unmatched_keys": unmatched_keys,
                        "next_step": (
                            "等待用户确认即可：服务端将按暂存参数直接执行写入，你无需任何后续调用"
                            if not auto_review else
                            ("全部校验通过，请以相同参数调用本工具 mode=commit" if report.all_ok
                             else "请处理上述非 ok 项（修正后重新 dry_run 或直接 commit）")
                        ),
                    },
                    metadata=metadata,
                )

            # 5. commit：硬错误拒绝
            hard_errors = [i for i in report.problem_items if i.status in ("not_found", "ambiguous")]
            if hard_errors:
                return ToolResult(
                    success=False,
                    error="存在必须处理的校验错误，请修正后重新 commit",
                    data={"dry_run_report": report.model_dump(), "summary": report.summary()},
                )

            return await self._commit(prepared, matched_fields, unmatched_keys,
                                      template_id, output_doc_id, doc_info, fill_mode, context)

        except Exception as e:
            logger.exception(f"表单填写失败: {e}")
            return ToolResult(success=False, error=f"表单填写失败: {str(e)}")

    # ──────────────────────────── 内部 ────────────────────────────

    @staticmethod
    def _prepare_all(snapshot: DocSnapshot, matched_fields: List[Dict[str, Any]],
                     fill_mode: str) -> List[PreparedFill]:
        """逐字段定位 + 准备写入（不写盘）"""
        prepared: List[PreparedFill] = []
        for match in matched_fields:
            field = match['field']
            value = match['value']
            location = field.get('location', {})

            # 列表字段（多行数据，如成员列表）
            if isinstance(value, list) and value and isinstance(value[0], dict):
                if location.get('is_header_based'):
                    prepared.append(prepare_table_rows_field(snapshot, field, value))
                else:
                    # 普通模式：只填第一个值
                    first = value[0]
                    first_value = str(first) if not isinstance(first, dict) \
                        else str(list(first.values())[0])
                    prepared.append(prepare_form_field(snapshot, field, first_value, fill_mode))
                continue

            prepared.append(prepare_form_field(snapshot, field, value, fill_mode))
        return prepared

    @staticmethod
    def _build_report(prepared: List[PreparedFill]) -> DryRunReport:
        report = DryRunReport()
        for p in prepared:
            if not p.ok:
                report.add(p.subject, p.status, p.detail)
            elif not p.after.strip():
                report.add(p.subject, "empty_value", f"值为空（当前: '{p.before[:30]}'）")
            else:
                report.add(p.subject, "ok", f"'{p.before[:30]}' → '{p.after[:30]}'")
        return report

    async def _commit(self, prepared: List[PreparedFill], matched_fields, unmatched_keys,
                      template_id: str, output_doc_id: str, doc_info: Dict[str, Any],
                      fill_mode: str, context: ToolContext) -> ToolResult:
        """版本化写入 + 逐字段 before/after 回报"""
        if output_doc_id:
            target_path, _, target_doc_id, _ = await lifecycle.resolve_edit_target(
                doc_info, None, context, origin_type="fill"
            )
            template_doc = None
        else:
            async with async_session() as db:
                result = await db.execute(select(Document).where(Document.id == template_id))
                template_doc = result.scalar_one_or_none()
            if not template_doc:
                return ToolResult(success=False, error=f"模板文档不存在: {template_id}")
            async with async_session() as db:
                output_doc = await document_versioning.create_root_output(
                    db,
                    user_id=context.user_id,
                    file_type=template_doc.file_type,
                    origin_type="fill",
                    source_doc=template_doc,
                    run_id=context.metadata.get("run_id"),
                    conversation_id=context.metadata.get("conversation_id"),
                )
                await db.commit()
            target_path = output_doc.file_path
            target_doc_id = str(output_doc.id)

        # 在目标文件上重新准备并写入（commit 复核：prepare 会再次定位，失败项跳过）
        changes: List[Dict[str, Any]] = []
        failed: List[str] = []
        with DocSnapshot.open(target_path, doc_info["file_type"]) as snapshot:
            reprepared = self._prepare_all(snapshot, matched_fields, fill_mode)
            for p in reprepared:
                if not p.ok:
                    failed.append(f"{p.subject}: {p.detail}")
                    continue
                result = p.apply()
                if result.ok:
                    changes.append({
                        "field": p.subject,
                        "before": (result.before or "")[:100],
                        "after": (result.after or "")[:100],
                    })
                else:
                    failed.append(f"{p.subject}: {result.error}")
            snapshot.save()

        reg = await lifecycle.finish_edit(target_doc_id, context)

        if template_id:
            async with async_session() as db:
                template_name = template_doc.original_filename if template_doc else template_id
                await lifecycle.record_template_usage(
                    db,
                    template_id=template_id,
                    template_name=template_name,
                    output_file_id=target_doc_id,
                    context=context,
                )

        logger.info(f"[FillFormTool] commit 完成: {len(changes)} 字段写入, {len(failed)} 失败")

        return ToolResult(
            success=True,
            data={
                "filled_fields": len(changes),
                "matched_fields": len(matched_fields),
                "unmatched_keys": unmatched_keys,
                "changes": changes,
                **({"failed_fields": failed} if failed else {}),
                **reg,
            },
            metadata={
                "template_id": template_id,
                "fill_mode": fill_mode,
                "is_new_file": not bool(output_doc_id),
            },
        )
