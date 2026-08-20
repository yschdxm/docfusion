"""
数据溯源（provenance）公共层

记录"填进模板的每行/每格数据来自哪个文档"：
- 取数时给每条记录打 `_source` 标签（随 record dict 走，穿 data_stash 不需要额外通道）
- 引擎物化行时剥掉标签写入文件，标签汇聚成行号 → 来源的映射（row_sources）
- commit 后由工具层把映射 + 取数口径（query/SQL/源文档）持久化为 provenance manifest

标签约定（record[SOURCE_KEY]）：
    {"doc_id": str|None, "doc_name": str, "origin": "sql_query"|"extract_records"|"inline",
     "detail": str|None,   # 面向用户的定位信息（源表名、原文摘录等），直接展示
     "meta": dict|None}    # 程序化辅助信息（chunk 序号、sheet 行号等），不进展示文案
"""

from typing import Any, Dict, List, Optional

SOURCE_KEY = "_source"

# 内部保留键：record 里允许存在但不属于数据列的键（打标、溯源辅助、源表物理序号）。
# __seq：xlsx 入库时的源行物理序号，SELECT * 时会被带出，需过滤不写进目标文件。
RESERVED_KEYS = (SOURCE_KEY, "chunk", "__seq")

# row_sources 压缩后的最大条目数。正常数据按 row_no 连续性合并后区间数 ≈ 来源切换次数（个位数），
# 该上限只在病态的逐行交替源（合并无法收敛）时兜底防 metadata_info 撑爆，正常不会触发。
MAX_ROW_SOURCE_RANGES = 20000


def tag_record(record: Dict[str, Any], *, doc_id: Optional[str], doc_name: str,
               origin: str, detail: Optional[str] = None,
               meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """给记录打来源标签（原地修改并返回）"""
    record[SOURCE_KEY] = {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "origin": origin,
        "detail": detail,
        "meta": meta or None,
    }
    return record


def get_source(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    src = record.get(SOURCE_KEY)
    return src if isinstance(src, dict) else None


def data_columns_of(records: List[Dict[str, Any]]) -> List[str]:
    """记录的数据列名（排除溯源标签等内部保留键）"""
    if not records:
        return []
    return [k for k in records[0].keys() if k not in RESERVED_KEYS]


def strip_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """剥掉内部保留键的记录副本（对外展示/序列化用）"""
    return {k: v for k, v in record.items() if k not in RESERVED_KEYS}


def source_label(src: Optional[Dict[str, Any]]) -> str:
    """来源短标签（UI 展示用）"""
    if not src:
        return ""
    label = src.get("doc_name") or "未知来源"
    detail = src.get("detail")
    return f"{label} · {detail}" if detail else label


def _same_origin(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    """两条来源是否同一文档+同一取数方式（忽略逐行 detail/meta 差异）"""
    if not a or not b:
        return a is b  # 同为 None 才算同
    return (a.get("doc_id"), a.get("doc_name"), a.get("origin")) == \
           (b.get("doc_id"), b.get("doc_name"), b.get("origin"))


def _source_base(src: Dict[str, Any]) -> Dict[str, Any]:
    """来源的文档级部分（不含逐行 detail/meta），区间共享"""
    return {k: src.get(k) for k in ("doc_id", "doc_name", "origin")}


def _row_no_of(src: Optional[Dict[str, Any]]) -> Optional[int]:
    if not src:
        return None
    row_no = (src.get("meta") or {}).get("row_no")
    return row_no if isinstance(row_no, int) else None


def compact_row_sources(row_sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把逐行的 [{row, source}] 压缩为连续区间。

    合并规则（比"source 完全相等"更智能——行号 detail 逐行不同，按相等性永远合并不了）：
    - 同文档+同取数方式 且目标行连续 且源行号也连续 → 合并为一段，源行号汇聚为区间
    - 源行号交错（筛选查询的源行在表中不连续）→ 拆成逐行段，保持"目标行 ↔ 源行"一一对应
    - 文档切换 / 目标行断档 → 起新区间
    区间结构：{from, to, source(文档级), row_nos(逐行源行号，与目标行 from..to 一一对应)}
    前端按 from..to 与 row_nos 逐行/逐段展示映射。超过上限时截断并标记 truncated（兜底）。
    """
    ranges: List[Dict[str, Any]] = []
    truncated = False
    for item in row_sources:
        row, src = item["row"], item.get("source")
        row_no = _row_no_of(src)
        if ranges and not truncated:
            last = ranges[-1]
            # 同源 且目标行连续 且源行号也连续（都有则等差，都无则顺延）→ 扩展为一段。
            # 源行号交错（如德州站点 sheet 306,308,…）时拆成逐行段，
            # 保证"目标行 X ↔ 源行 Y"一一对应，不把一堆离散行号堆在一个区间里。
            if _same_origin(last["source"], src) and row == last["to"] + 1:
                last_nos = last.get("row_nos")
                if row_no is not None and last_nos:
                    if row_no == last_nos[-1] + 1:
                        last["to"] = row
                        last_nos.append(row_no)
                        continue
                elif row_no is None and not last_nos:
                    last["to"] = row
                    continue
        if len(ranges) >= MAX_ROW_SOURCE_RANGES:
            truncated = True
            continue
        entry: Dict[str, Any] = {
            "from": row, "to": row,
            "source": _source_base(src) if src else None,
        }
        if row_no is not None:
            entry["row_nos"] = [row_no]
        ranges.append(entry)
    return {"ranges": ranges, "truncated": truncated}
