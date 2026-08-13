"""
模板结构探测结果的进程内缓存

get_template_structure 探测出的结构（含 field_id 分配）在这里暂存，
fill_form 等写入工具通过 (doc_id, sha256) 键复用同一份结果，避免：
- 同一次填写流程中重复调用 LLM 做字段检测
- Agent 看到的字段与写入工具实际使用的字段不一致

文档内容变化（产生新版本）会改变 sha256，缓存自然失效。
"""

import time
from typing import Any, Dict, Optional

_TTL_SECONDS = 1800  # 30 分钟
_cache: Dict[str, Dict[str, Any]] = {}


def make_key(kind: str, doc_id: str, sha256: Optional[str]) -> str:
    return f"{kind}:{doc_id}:{sha256 or 'nosum'}"


def get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > _TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return entry["value"]


def set(key: str, value: Any) -> None:
    _cleanup()
    _cache[key] = {"ts": time.time(), "value": value}


def invalidate(key: str) -> None:
    _cache.pop(key, None)


def _cleanup() -> None:
    if len(_cache) < 256:
        return
    now = time.time()
    expired = [k for k, v in _cache.items() if now - v["ts"] > _TTL_SECONDS]
    for k in expired:
        _cache.pop(k, None)
    # 仍超限则淘汰最旧的一半
    if len(_cache) >= 256:
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1]["ts"])[: len(_cache) // 2]:
            _cache.pop(k, None)
