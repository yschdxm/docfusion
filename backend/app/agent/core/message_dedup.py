"""
用户消息幂等去重（client_message_id）

前端 SSE 连接级重试会原样重发请求体；若首次请求已创建任务但响应头（X-Task-Id）
未送达（页面切出/网络中断），重试会缺少 task_id 而再次走"新任务"分支，
导致同一用户消息被重复执行。按 (conversation_id, client_message_id) 记录
已创建的任务，命中则转为订阅而非新建。

纯内存实现（单进程部署够用）。TTL 略大于 task_manager.TASK_TTL(10min)，
保证去重记录比任务存活久——命中时原任务一定还在 task_manager 里可回放。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_TTL = timedelta(minutes=15)
_store: Dict[Tuple[str, str], dict] = {}  # (conversation_id, client_message_id) → {task_id, expires_at}


def register(conversation_id: str, client_message_id: str, task_id: str) -> None:
    """记录一次已创建的任务（在任务创建成功后立即调用）"""
    _cleanup()
    _store[(conversation_id, client_message_id)] = {
        "task_id": task_id,
        "expires_at": datetime.utcnow() + _TTL,
    }
    logger.info(
        f"[message_dedup] 注册幂等键: conv={conversation_id} "
        f"cmid={client_message_id[:8]} task={task_id[:8]}"
    )


def lookup(conversation_id: str, client_message_id: str) -> Optional[str]:
    """查找该幂等键对应的 task_id，未记录或已过期返回 None"""
    entry = _store.get((conversation_id, client_message_id))
    if not entry:
        return None
    if datetime.utcnow() > entry["expires_at"]:
        del _store[(conversation_id, client_message_id)]
        return None
    return entry["task_id"]


def _cleanup() -> None:
    now = datetime.utcnow()
    for key in [k for k, v in _store.items() if now > v["expires_at"]]:
        del _store[key]
