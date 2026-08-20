"""
数据源获取引擎（从 fill_table_tool 抽取）

把"从源文档批量查询数据"的确定性流程独立出来：
分批拉取（LIMIT/OFFSET）、去重、上限保护。
"""

import logging
from typing import Any, Dict, List, Optional

from app.agent.document_engine.provenance import data_columns_of, strip_record

logger = logging.getLogger(__name__)

_MAX_TOTAL_ROWS = 50000  # 最多获取5万行，防止无限循环
_BATCH_SIZE = 5000
_FIRST_BATCH_LIMIT = 10000  # SQL 服务单次查询的 LIMIT 上限


async def fetch_all_data(
    sql_service,
    augmented_query: str,
    doc_ids: List[str],
    out_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """分批获取全部数据

    1. 首次查询获取数据
    2. 如果达到 LIMIT 上限，尝试分批获取更多
    3. 最多 _MAX_TOTAL_ROWS 条，防止无限循环

    out_meta：传入 dict 时回填实际执行的 SQL（供调用方透给主 LLM 核对取数口径）
    """
    query_result = await sql_service.generate_and_execute(
        question=augmented_query,
        doc_ids=doc_ids,
        max_retries=3,
    )

    if out_meta is not None:
        out_meta["sql"] = query_result.get("sql", "")

    records = query_result.get("records", [])
    total_fetched = len(records)

    if total_fetched >= _FIRST_BATCH_LIMIT:
        logger.info(f"[datasource] 首次查询返回{total_fetched}条，可能还有更多数据，尝试分批获取")

        offset = total_fetched
        while total_fetched < _MAX_TOTAL_ROWS:
            batch_query = (
                f"{augmented_query}\n\n"
                f"请使用 OFFSET {offset} LIMIT {_BATCH_SIZE} 获取下一批数据"
            )
            batch_result = await sql_service.generate_and_execute(
                question=batch_query,
                doc_ids=doc_ids,
                max_retries=2,
            )
            batch_records = batch_result.get("records", [])
            if not batch_records:
                break

            records.extend(batch_records)
            total_fetched += len(batch_records)
            offset += len(batch_records)
            logger.info(f"[datasource] 分批获取: 已获取 {total_fetched} 行")

            if len(batch_records) < _BATCH_SIZE:
                break

    # 去重
    seen = set()
    unique_records = []
    for record in records:
        key = tuple(sorted((k, str(v)) for k, v in record.items()))
        if key not in seen:
            seen.add(key)
            unique_records.append(record)

    logger.info(f"[datasource] 最终获取: {len(unique_records)} 条唯一记录（原始 {len(records)} 条）")
    return unique_records


def build_data_summary(records: List[Dict[str, Any]], template_headers: List[str]) -> str:
    """构建数据摘要：列质量统计 + 前10行 + 中间5行 + 末尾5行（供 LLM 审核/生成映射）"""
    import json

    if not records:
        return "无数据"

    total = len(records)
    # 排除溯源标签等内部键，只统计数据列
    columns = data_columns_of(records)

    null_counts = {col: 0 for col in columns}
    unique_counts = {col: set() for col in columns}
    for record in records:
        for col in columns:
            val = record.get(col)
            if val is None or str(val).strip() == "" or str(val) == "None":
                null_counts[col] += 1
            else:
                unique_counts[col].add(str(val))
    unique_counts = {col: len(vals) for col, vals in unique_counts.items()}

    lines = [f"共 {total} 行数据，{len(columns)} 列"]
    lines.append(f"源数据列名: {columns}")
    lines.append(f"模板表头:   {template_headers}")
    lines.append("")

    lines.append("=== 列信息摘要 ===")
    for col in columns:
        null_pct = null_counts[col] / total * 100 if total > 0 else 0
        lines.append(f"  {col}: 唯一值 {unique_counts[col]}，空值 {null_counts[col]} ({null_pct:.1f}%)")
    lines.append("")

    head_count = min(10, total)
    lines.append(f"=== 前 {head_count} 行 ===")
    for i, record in enumerate(records[:head_count]):
        lines.append(f"行{i + 1}: {json.dumps(strip_record(record), ensure_ascii=False)}")

    if total > 20:
        mid_start = total // 2 - 2
        lines.append(f"\n=== 中间第 {mid_start + 1}-{mid_start + 5} 行 ===")
        for i, record in enumerate(records[mid_start:mid_start + 5]):
            lines.append(f"行{mid_start + i + 1}: {json.dumps(strip_record(record), ensure_ascii=False)}")

    if total > 10:
        lines.append("\n=== 末尾 5 行 ===")
        for i, record in enumerate(records[-5:], start=total - 4):
            lines.append(f"行{i + 1}: {json.dumps(strip_record(record), ensure_ascii=False)}")

    return "\n".join(lines)
