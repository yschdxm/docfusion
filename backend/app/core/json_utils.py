"""JSON 安全化工具：把 Python 对象递归转换为可 JSON 序列化的结构

PG numeric 列会返回 Decimal，直接 json.dumps / SQLAlchemy JSON 列插入都会
TypeError（曾导致 SSE 事件流中断 + 消息落库丢失）。所有跨边界（SSE 事件、
DB JSON 列、LLM 可见数据）的序列化统一走这里。
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional


def jsonable(obj: Any) -> Any:
    """递归转换：Decimal→float，datetime/date→isoformat，set/tuple→list，其余未知类型→str"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    return str(obj)


# ============================================================
# 时间序列化：DB 存的是 naive UTC（datetime.utcnow），
# 序列化给前端时必须带时区（或按 UTC 算 epoch），
# 否则 JS new Date()/naive.timestamp() 会按本地时区误解，显示快/慢 8 小时
# ============================================================

def as_local(dt: Optional[datetime]) -> Optional[datetime]:
    """naive（视为 UTC）→ 本地时区 aware；aware 输入原样转本地"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def local_iso(dt: Optional[datetime]) -> Optional[str]:
    """序列化为带本地偏移的 ISO 字符串（如 2026-08-18T13:26:56+08:00），JS 可正确解析"""
    local = as_local(dt)
    return local.isoformat() if local else None


def epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    """按真实 UTC 时刻算 epoch 毫秒（naive 输入视为 UTC）"""
    local = as_local(dt)
    return int(local.timestamp() * 1000) if local else None


def epoch_s(dt: Optional[datetime]) -> Optional[int]:
    """按真实 UTC 时刻算 epoch 秒"""
    local = as_local(dt)
    return int(local.timestamp()) if local else None
