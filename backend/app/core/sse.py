"""
SSE 工具函数 - 统一 Server-Sent Events 响应格式

所有 SSE 端点（agent 流、文档进度流等）共用：
- 标准响应头（禁缓存、禁 nginx 缓冲）
- 标准三字段格式（id/event/data）
- keepalive 心跳注释行
"""

import json
from datetime import date, datetime
from typing import Optional


# 标准 SSE 响应头
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# 心跳注释行（防止代理断连）
SSE_KEEPALIVE = ": keepalive\n\n"


def format_sse(data: dict, event: Optional[str] = None, event_id: Optional[int] = None) -> str:
    """格式化一条 SSE 消息（标准三字段）

    Args:
        data: data 字段的 JSON 内容
        event: event 字段（事件类型），None 则省略
        event_id: id 字段（事件序号，用于 Last-Event-ID 断点续传），None 则省略
    """
    def json_serializer(obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, default=json_serializer)}")
    return "\n".join(lines) + "\n\n"
