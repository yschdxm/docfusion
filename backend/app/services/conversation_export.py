"""
对话导出（Markdown 生成器）

把会话（用户消息、AI 回复、执行步骤树、操作卡片、任务统计）渲染为 Markdown，
用于留档 / 记录 / debug。由 GET /conversations/{id}/export 调用。
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.models.document import Conversation, Message

# 长文本截断阈值（防止单条消息导出膨胀到数 MB）
_THINKING_LIMIT = 500
_JSON_LIMIT = 300

_ROLE_LABELS = {"user": "用户", "assistant": "AI"}

_STATUS_LABELS = {
    "pending": "等待中",
    "running": "执行中",
    "completed": "已完成",
    "error": "失败",
}

_ACTION_STATUS_LABELS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "cancelled": "已取消",
}


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + " …(已截断)"


def _json_block(value: Any, limit: int = _JSON_LIMIT) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(value)
    return _truncate(text, limit)


def _fmt_time(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime):
        # DB 存的是 UTC 朴素时间，转为本地时区显示（与"导出时间"一致）
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def _render_step(step: Dict[str, Any], depth: int) -> List[str]:
    """递归渲染执行步骤（结构对齐前端 AgentStep / 后端 StepAccumulator）"""
    indent = "  " * depth
    lines: List[str] = []
    name = step.get("name") or step.get("toolName") or step.get("type") or "步骤"
    status = _STATUS_LABELS.get(step.get("status"), step.get("status") or "")
    progress = step.get("progress")
    suffix = f"（{status}）" if status else ""
    if progress is not None and step.get("status") == "running":
        suffix = f"（{status} {progress}%）"
    lines.append(f"{indent}- **{name}** {suffix}".rstrip())

    if step.get("errorMessage"):
        lines.append(f"{indent}  - 错误：{_truncate(step['errorMessage'], _THINKING_LIMIT)}")
    if step.get("thinkingContent"):
        lines.append(f"{indent}  - 思考：{_truncate(step['thinkingContent'], _THINKING_LIMIT)}")
    if step.get("streamingReply"):
        lines.append(f"{indent}  - 回复：{_truncate(step['streamingReply'], _THINKING_LIMIT)}")
    if step.get("toolParams"):
        lines.append(f"{indent}  - 参数：`{_json_block(step['toolParams'])}`")
    if step.get("toolResult") is not None:
        lines.append(f"{indent}  - 结果：`{_json_block(step['toolResult'])}`")

    for child in step.get("children") or []:
        lines.extend(_render_step(child, depth + 1))
    return lines


def _render_action_data(action_data: Dict[str, Any]) -> List[str]:
    """渲染操作卡片（确认卡片 / 完成卡片 / 失败卡片）"""
    lines = ["### 操作卡片", ""]
    action_type = action_data.get("action_type", "未知")

    if action_type == "confirm_fill":
        status = _ACTION_STATUS_LABELS.get(action_data.get("status"), action_data.get("status") or "未知")
        lines.append(f"- 类型：写入确认（confirm_fill） · 状态：{status}")
        if action_data.get("action_id"):
            lines.append(f"- action_id：`{action_data['action_id']}`")
        if action_data.get("summary"):
            lines.append(f"- 摘要：{action_data['summary']}")
        report = action_data.get("dry_run_report")
        if report:
            total = report.get("total", 0)
            ok = report.get("ok_count", 0)
            lines.append(f"- dry_run：共 {total} 项，通过 {ok} 项")
            for item in report.get("items") or []:
                if item.get("status") != "ok":
                    detail = f"：{item['detail']}" if item.get("detail") else ""
                    lines.append(f"  - [{item.get('status')}] {item.get('subject')}{detail}")
    elif action_type == "completed":
        lines.append("- 类型：写入完成（completed）")
        if action_data.get("filled_file_url"):
            lines.append(f"- 输出文件：[下载]({action_data['filled_file_url']})")
        if action_data.get("filled_file_id"):
            lines.append(f"- 文件ID：`{action_data['filled_file_id']}`")
    elif action_type == "failed":
        lines.append("- 类型：失败（failed）")
        if action_data.get("error"):
            lines.append(f"- 错误：{action_data['error']}")
    else:
        lines.append(f"- 类型：{action_type}")
        lines.append(f"- 数据：`{_json_block(action_data)}`")
    return lines


def _render_task_stats(stats: Dict[str, Any]) -> str:
    """任务统计一行汇总，缺失字段跳过"""
    parts: List[str] = []
    duration_ms = stats.get("duration_ms")
    if duration_ms is not None:
        parts.append(f"耗时 {duration_ms / 1000:.1f}s")
    if stats.get("total_tokens") is not None:
        token_detail = (
            f"prompt {stats.get('prompt_tokens', 0)} / "
            f"completion {stats.get('completion_tokens', 0)}"
        )
        if stats.get("cached_tokens"):
            token_detail += f" / cached {stats['cached_tokens']}"
        if stats.get("reasoning_tokens"):
            token_detail += f" / reasoning {stats['reasoning_tokens']}"
        parts.append(f"tokens {stats['total_tokens']}（{token_detail}）")
    if stats.get("llm_calls") is not None:
        parts.append(f"LLM 调用 {stats['llm_calls']} 次")
    if stats.get("iterations") is not None:
        parts.append(f"迭代 {stats['iterations']} 轮")
    return " · ".join(parts)


def render_markdown(conv: Conversation, messages: List[Message]) -> str:
    """渲染完整会话为 Markdown"""
    lines: List[str] = [
        f"# {conv.title or '对话记录'}",
        "",
        f"- 会话ID：`{conv.id}`",
        f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 会话创建：{_fmt_time(conv.created_at)}",
        f"- 消息数：{len(messages)}",
        "",
        "---",
        "",
    ]

    for idx, msg in enumerate(messages, 1):
        role = _ROLE_LABELS.get(msg.role, msg.role)
        lines.append(f"## [{idx}] {role} · {_fmt_time(msg.created_at)}")
        lines.append("")
        if msg.content:
            lines.append(msg.content)
            lines.append("")
        if msg.steps:
            lines.append("### 执行步骤")
            lines.append("")
            for step in msg.steps:
                lines.extend(_render_step(step, 0))
            lines.append("")
        if msg.action_data:
            lines.extend(_render_action_data(msg.action_data))
            lines.append("")
        if msg.task_stats:
            stats_line = _render_task_stats(msg.task_stats)
            if stats_line:
                lines.append("### 任务统计")
                lines.append("")
                lines.append(stats_line)
                lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
