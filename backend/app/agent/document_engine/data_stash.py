"""
查询数据暂存（显式 token 制）

plan 工具查到的源数据可能达数万行，无法也不应让 LLM 在上下文中搬运。
plan 返回 data_token，execute 凭 token 取数。

与旧实现的区别（旧实现被移除的原因）：
- 旧：类级缓存，key = hash(query)，LLM 无感知、跨进程失效、命中行为隐式
- 新：token 显式传递给 LLM，必须随 execute 回传，无隐藏状态；TTL 兜底防泄漏
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

_TTL = timedelta(minutes=30)
_store: Dict[str, Dict[str, Any]] = {}


def put(records: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> str:
    """暂存记录，返回 data_token"""
    _cleanup()
    token = uuid4().hex[:16]
    _store[token] = {
        "records": records,
        "meta": meta or {},
        "expires_at": datetime.utcnow() + _TTL,
    }
    logger.info(f"[data_stash] 暂存 {len(records)} 行, token={token}")
    return token


def get(token: str) -> Optional[Dict[str, Any]]:
    """按 token 取数；过期或不存在返回 None"""
    entry = _store.get(token)
    if not entry:
        return None
    if datetime.utcnow() > entry["expires_at"]:
        del _store[token]
        return None
    return entry


def _cleanup() -> None:
    now = datetime.utcnow()
    for key in [k for k, v in _store.items() if now > v["expires_at"]]:
        del _store[key]
