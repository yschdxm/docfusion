"""
填写引擎：dry_run（纯确定性校验，不写盘）与 commit（物化写入 + 逐格 diff）

- TableFillPlan（统计表）：LLM 给出 column_map（模板表头→源列名），引擎校验列对齐、
  物化数据行、写盘，并报告行级 diff
- CellFill（表单/交叉表/指定位置）：引擎逐格解析地址、校验、写入，逐格 before/after
"""

import logging
from typing import Any, Dict, List, Tuple

from app.agent.document_engine import ops
from app.agent.document_engine.address import (
    AddressResolver,
    DocxTableAddr,
    XlsxSheetAddr,
    describe_address,
)
from app.agent.document_engine.headers import (
    get_template_headers,
    match_value_for_header,
    resolve_xlsx_headers,
)
from app.agent.document_engine.mapping import CellFill, DryRunReport, TableFillPlan
from app.agent.document_engine.snapshot import DocSnapshot

logger = logging.getLogger(__name__)


# ──────────────────────────── TableFillPlan ────────────────────────────

def dry_run_table_fill(snapshot: DocSnapshot, plan: TableFillPlan) -> DryRunReport:
    """校验统计表填写计划：目标存在、表头对齐、列映射有效、数据非空"""
    report = DryRunReport()
    target_desc = describe_address(plan.target)

    # 1. 目标解析
    resolved = AddressResolver.resolve(plan.target, snapshot)
    if not resolved.ok:
        report.add(target_desc, resolved.status, resolved.detail)
        return report
    report.add(target_desc, "ok")

    # 2. 模板表头
    headers = _target_headers(snapshot, plan.target)
    if not headers:
        report.add(target_desc, "not_found", "目标表格没有可用表头")
        return report

    # 3. 列映射校验：模板表头必须存在；源列名必须在数据列中
    data_columns = list(plan.data[0].keys()) if plan.data else []
    mapped_headers = set(plan.column_map.keys())
    for header, source_col in plan.column_map.items():
        if header not in headers:
            report.add(f"表头「{header}」", "not_found",
                       f"模板中不存在该表头，可用表头: {headers}")
            continue
        if source_col and source_col not in data_columns:
            report.add(f"映射 {header} ← {source_col}", "not_found",
                       f"源数据中不存在列「{source_col}」，可用列: {data_columns}")
            continue
        report.add(f"映射 {header} ← {source_col}", "ok")

    unmapped = [h for h in headers if h not in mapped_headers
                and not h.startswith("Column_")]
    for header in unmapped:
        report.add(f"表头「{header}」", "empty_value",
                   "未在 column_map 中，将尝试自动匹配兜底（精确→大小写→包含）")

    # 4. 数据校验
    if not plan.data:
        report.add("data", "empty_value", "记录数组为空，将不写入任何数据行")
    else:
        report.add("data", "ok", f"将写入 {len(plan.data)} 行（fill_mode={plan.fill_mode}）")

    return report


def commit_table_fill(snapshot: DocSnapshot, plan: TableFillPlan) -> Tuple[List[Dict[str, Any]], DryRunReport]:
    """执行统计表填写。先复核（dry_run），硬错误（目标/映射 not_found）则拒绝写入。

    Returns:
        (changes, report) —— changes 含行数与样本 diff
    """
    report = dry_run_table_fill(snapshot, plan)
    # 表头/映射的列级问题不整体拒绝（该列填空继续）；目标不存在/歧义才拒绝写入
    hard_errors = [i for i in report.problem_items if i.status in ("not_found", "ambiguous")
                   and not i.subject.startswith(("表头「", "映射 "))]
    if hard_errors:
        return [], report

    resolved = AddressResolver.resolve(plan.target, snapshot)
    headers = _target_headers(snapshot, plan.target)
    row_values = make_row_values_fn(headers, plan)

    changes: List[Dict[str, Any]] = []
    if isinstance(plan.target, XlsxSheetAddr):
        changes = _commit_xlsx_rows(snapshot, resolved.target, plan, headers, row_values)
    elif isinstance(plan.target, DocxTableAddr):
        changes = _commit_docx_rows(resolved.target, plan, headers, row_values)

    return changes, report


def make_row_values_fn(headers: List[str], plan: TableFillPlan):
    """生成"记录 → 行值"的物化函数（commit 与 preview 共用）"""
    def row_values(record: Dict[str, Any]) -> List[str]:
        values = []
        for header in headers:
            source_col = plan.column_map.get(header)
            if source_col:
                value = record.get(source_col)
            else:
                # 未映射的表头走三级自动匹配兜底
                value = match_value_for_header(record, header) or None
            values.append("" if value is None else str(value))
        return values
    return row_values


def preview_table_fill(snapshot: DocSnapshot, plan: TableFillPlan, max_rows: int = 500) -> Dict[str, Any]:
    """物化预览：返回实际将写入的表头与行值（不写盘）

    行数上限 500（preview 只进确认卡片/UI，不进 LLM 上下文），前端分页展示；
    超过上限时截断并由 total_rows 提示实际总数。
    """
    headers = _target_headers(snapshot, plan.target)
    row_values = make_row_values_fn(headers, plan)
    rows = [row_values(record) for record in plan.data[:max_rows]]
    return {
        "headers": headers,
        "rows": rows,
        "total_rows": len(plan.data),
        "fill_mode": plan.fill_mode,
        "target": describe_address(plan.target),
    }


def _target_headers(snapshot: DocSnapshot, target) -> List[str]:
    """目标表格的表头"""
    if isinstance(target, XlsxSheetAddr):
        headers, _ = resolve_xlsx_headers(snapshot.path, target.sheet, target.header_row)
        return headers
    if isinstance(target, DocxTableAddr):
        return get_template_headers(snapshot.path, "docx", target.table_index)
    return []


def _clear_xlsx_below_header(ws, header_row: int) -> None:
    """清空表头以下的数据区（overwrite 用）。

    严禁逐行 delete_rows：openpyxl 每删一行都要全量调整合并区域，
    在病态模板（27000 行 × 5 万条合并区域，实测存在）上会卡死几十分钟，
    且同步执行会阻塞整个事件循环（曾把后端打到无响应）。
    正确姿势：先丢弃完全位于表头以下的合并区域，再一次性块删除数据行。
    """
    if ws.max_row <= header_row:
        return
    ranges = list(ws.merged_cells.ranges)
    if ranges:
        keep = [r for r in ranges if r.max_row <= header_row]
        dropped = len(ranges) - len(keep)
        if dropped:
            ws.merged_cells.ranges = keep
            logger.info(f"[Fill] overwrite 清空数据区：丢弃表头以下合并区域 {dropped} 个，保留 {len(keep)} 个")
    ws.delete_rows(header_row + 1, ws.max_row - header_row)


def _commit_xlsx_rows(snapshot: DocSnapshot, ws, plan: TableFillPlan,
                      headers: List[str], row_values) -> List[Dict[str, Any]]:
    """xlsx 行物化：overwrite 删除表头以下数据行；append 直接追加"""
    _, header_row = resolve_xlsx_headers(
        snapshot.path, plan.target.sheet, plan.target.header_row
    )
    if not headers:
        header_row = plan.target.header_row or 1

    if plan.fill_mode == "overwrite":
        _clear_xlsx_below_header(ws, header_row)

    filled = 0
    sample = []
    for record in plan.data:
        ws.append(row_values(record))
        if filled < 3:
            sample.append({"row": ws.max_row, "values": row_values(record)})
        filled += 1

    return [{
        "op": "table_fill",
        "target": describe_address(plan.target),
        "fill_mode": plan.fill_mode,
        "filled_rows": filled,
        "sample": sample,
    }]


def _commit_docx_rows(table, plan: TableFillPlan,
                      headers: List[str], row_values) -> List[Dict[str, Any]]:
    """docx 行物化：overwrite 清空数据行后逐行写入；append 空行优先再追加"""
    filled = 0
    sample = []

    if plan.fill_mode == "overwrite":
        old_rows = list(table.rows[1:])
        for row in old_rows:
            ops.delete_row(table, row)
        for record in plan.data:
            values = row_values(record)
            ops.append_row(table, values)
            if filled < 3:
                sample.append({"row": filled + 1, "values": values})
            filled += 1
    else:
        # 空行优先
        empty_rows = [row for row in table.rows[1:] if ops.is_empty_row(row)]
        data_index = 0
        for row in empty_rows:
            if data_index >= len(plan.data):
                break
            values = row_values(plan.data[data_index])
            for i, value in enumerate(values):
                if i < len(row.cells):
                    ops.set_cell_text(row.cells[i], value)
            if filled < 3:
                sample.append({"row": data_index + 1, "values": values})
            filled += 1
            data_index += 1
        for record in plan.data[data_index:]:
            values = row_values(record)
            ops.append_row(table, values)
            if filled < 3:
                sample.append({"row": filled + 1, "values": values})
            filled += 1

    return [{
        "op": "table_fill",
        "target": describe_address(plan.target),
        "fill_mode": plan.fill_mode,
        "filled_rows": filled,
        "sample": sample,
    }]


# ──────────────────────────── CellFill ────────────────────────────

def dry_run_cell_fills(snapshot: DocSnapshot, fills: List[CellFill]) -> DryRunReport:
    """逐格校验：地址可解析、报告当前值"""
    report = DryRunReport()
    for fill in fills:
        desc = describe_address(fill.target)
        resolved = AddressResolver.resolve(fill.target, snapshot)
        if not resolved.ok:
            report.add(desc, resolved.status, resolved.detail)
            continue
        current = _read_current_value(fill.target, resolved.target)
        if fill.value is None or str(fill.value).strip() == "":
            report.add(desc, "empty_value", f"值为空（当前内容: '{current[:30]}'），将清空/留空")
            continue
        report.add(desc, "ok", f"当前内容: '{current[:30]}' → 新值: '{str(fill.value)[:30]}'")
    return report


def commit_cell_fills(snapshot: DocSnapshot, fills: List[CellFill]) -> Tuple[List[Dict[str, Any]], DryRunReport]:
    """逐格写入。地址无法解析的格子跳过并在报告中保留。"""
    report = DryRunReport()
    changes: List[Dict[str, Any]] = []

    for fill in fills:
        desc = describe_address(fill.target)
        resolved = AddressResolver.resolve(fill.target, snapshot)
        if not resolved.ok:
            report.add(desc, resolved.status, resolved.detail)
            continue

        result = _apply_cell_fill(fill.target, resolved.target, fill.value)
        if result.ok:
            report.add(desc, "ok")
            changes.append({
                "op": "set_cell",
                "target": desc,
                "before": result.before[:300],
                "after": result.after[:300],
            })
        else:
            report.add(desc, "not_found", result.error)

    return changes, report


def preview_cell_fills(snapshot: DocSnapshot, fills: List[CellFill]) -> List[Dict[str, Any]]:
    """逐格预览：地址、当前值、将写入的值（不写盘）"""
    preview = []
    for fill in fills:
        desc = describe_address(fill.target)
        resolved = AddressResolver.resolve(fill.target, snapshot)
        if not resolved.ok:
            preview.append({"target": desc, "before": "", "after": str(fill.value or ""),
                            "status": resolved.status})
            continue
        current = _read_current_value(fill.target, resolved.target)
        preview.append({"target": desc, "before": current[:100],
                        "after": "" if fill.value is None else str(fill.value)[:100],
                        "status": "ok"})
    return preview


def _read_current_value(addr, target) -> str:
    """读取目标当前值（用于报告）"""
    from app.agent.document_engine.address import (
        ContentControlAddr, DocxParagraphAddr, DocxTableCellAddr, XlsxCellAddr,
    )

    if isinstance(addr, XlsxCellAddr):
        return "" if target.value is None else str(target.value)
    if isinstance(addr, (DocxTableCellAddr,)):
        return target.text.strip()
    if isinstance(addr, DocxParagraphAddr):
        return target.text.strip()
    if isinstance(addr, ContentControlAddr):
        from docx.oxml.ns import qn
        return "".join(t.text or "" for t in target.findall('.//' + qn('w:t'))).strip()
    return ""


def _apply_cell_fill(addr, target, value: Any) -> ops.OpResult:
    """按地址类型分发写入"""
    from app.agent.document_engine.address import (
        ContentControlAddr, DocxParagraphAddr, DocxTableCellAddr, XlsxCellAddr,
    )

    text = "" if value is None else str(value)
    if isinstance(addr, XlsxCellAddr):
        return ops.set_xlsx_cell(target, value)
    if isinstance(addr, DocxTableCellAddr):
        return ops.set_cell_text(target, text)
    if isinstance(addr, DocxParagraphAddr):
        return ops.set_paragraph_text(target, text)
    if isinstance(addr, ContentControlAddr):
        return ops.set_content_control_text(target, text)
    return ops.OpResult.fail("未知地址", f"不支持的地址类型: {type(addr).__name__}")
