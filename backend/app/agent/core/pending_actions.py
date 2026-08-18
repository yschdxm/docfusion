"""
待确认操作暂存（pending actions）

人工确认模式（auto_review=False）下，dry_run 通过后的完整提交参数按 action_id 暂存：
- 确认时 LLM 只需传 confirm_action_id，无需跨 run 复制完整参数（data_token/mapping）
- 取消时标记状态，防止过期参数被误提交
- 卡片状态（pending/confirmed/cancelled）与消息 action_data 同步，供前端持久化展示
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

_TTL = timedelta(minutes=30)
_store: Dict[str, Dict[str, Any]] = {}
_by_conversation: Dict[str, str] = {}  # conversation_id → 最新 action_id


def put(*, tool: str, params: Dict[str, Any], summary: str = "",
        conversation_id: Optional[str] = None) -> str:
    """暂存待确认的提交参数，返回 action_id"""
    _cleanup()
    action_id = uuid4().hex[:16]
    _store[action_id] = {
        "tool": tool,
        "params": params,
        "summary": summary,
        "status": "pending",
        "conversation_id": conversation_id,
        "expires_at": datetime.utcnow() + _TTL,
    }
    if conversation_id:
        _by_conversation[conversation_id] = action_id
    logger.info(f"[pending_actions] 暂存待确认操作: tool={tool} action_id={action_id}")
    return action_id


def latest_pending(conversation_id: str) -> Optional[tuple]:
    """该对话最新的 pending 操作，返回 (action_id, entry) 或 None

    用于把用户手打的"确认"路由到直接提交路径。
    """
    action_id = _by_conversation.get(conversation_id)
    if not action_id:
        return None
    entry = get(action_id)
    if not entry or entry["status"] != "pending":
        return None
    return action_id, entry


def get(action_id: str) -> Optional[Dict[str, Any]]:
    """按 action_id 取暂存（仅 pending 状态可用）"""
    entry = _store.get(action_id)
    if not entry:
        return None
    if datetime.utcnow() > entry["expires_at"]:
        del _store[action_id]
        return None
    return entry


def resolve(action_id: str, status: str) -> bool:
    """标记操作终态（confirmed/cancelled）。已终结或过期的操作返回 False"""
    entry = get(action_id)
    if not entry or entry["status"] != "pending":
        return False
    entry["status"] = status
    logger.info(f"[pending_actions] 操作 {action_id} → {status}")
    return True


def retarget_pending(conversation_id: Optional[str], template_id: str, output_doc_id: str) -> int:
    """把同一会话中针对同一模板的其它 pending 操作改指到已产出的输出文档

    多表分别确认场景：第一次确认从模板创建了输出文件，后续表的确认应写入
    同一逻辑文档（版本叠加），而不是各自从模板新建输出变成多个文件。
    返回改写的操作数。
    """
    if not conversation_id or not template_id or not output_doc_id:
        return 0
    count = 0
    for entry in _store.values():
        if (entry["status"] == "pending"
                and entry.get("conversation_id") == conversation_id
                and entry["params"].get("template_id") == template_id):
            entry["params"]["output_doc_id"] = output_doc_id
            count += 1
    if count:
        logger.info(
            f"[pending_actions] {count} 个待确认操作改指输出文档 {output_doc_id[:8]}（同模板 {template_id[:8]}）"
        )
    return count


def _cleanup() -> None:
    now = datetime.utcnow()
    for key in [k for k, v in _store.items() if now > v["expires_at"]]:
        del _store[key]
