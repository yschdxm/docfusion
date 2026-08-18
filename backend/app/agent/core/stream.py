"""
Agent 事件类型定义

SSE 协议规范（标准三字段）：
    id: <seq>            ← 单调递增序号，由 TaskEventLog 分配；重连用 Last-Event-ID 续传
    event: <event_type>
    data: <json>         ← 包含 event_type/step_id/timestamp + 业务数据

事件传输见 app/agent/core/event_log.py (TaskEventLog)。

注意：前端 agentStreamService.ts 依赖本文件的 event_type 取值，修改时需同步。
"""

import json
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
import logging


logger = logging.getLogger(__name__)


class AgentEventType(str, Enum):
    """Agent事件类型"""

    # 思考事件
    THINKING_START = "thinking_start"      # 开始思考
    THINKING_CHUNK = "thinking_chunk"      # 思考内容片段
    THINKING_END = "thinking_end"          # 思考结束

    # 工具事件
    TOOL_CALL = "tool_call"                # 调用工具
    TOOL_RESULT = "tool_result"            # 工具返回结果
    TOOL_ERROR = "tool_error"              # 工具执行错误

    # 步骤事件
    STEP_START = "step_start"              # 开始执行步骤
    STEP_PROGRESS = "step_progress"        # 步骤进度更新
    STEP_END = "step_end"                  # 步骤结束

    # 数据检索事件
    DATA_RETRIEVAL_START = "data_retrieval_start"    # 开始数据检索
    DATA_RETRIEVAL_PROGRESS = "data_retrieval_progress"  # 数据检索进度
    DATA_RETRIEVAL_END = "data_retrieval_end"        # 数据检索结束

    # 填表事件
    FILL_TABLE_START = "fill_table_start"    # 开始填表
    FILL_TABLE_PROGRESS = "fill_table_progress"  # 填表进度
    FILL_TABLE_END = "fill_table_end"        # 填表结束

    # 内容事件
    CONTENT_CHUNK = "content_chunk"          # 回复内容片段
    CONTENT_END = "content_end"              # 回复内容结束
    ASSISTANT_MESSAGE = "assistant_message"  # AI助手完整消息（中间步骤）

    # 动作事件
    ACTION_REQUIRED = "action_required"    # 需要用户确认
    ACTION_CONFIRMED = "action_confirmed"  # 用户已确认
    ACTION_CANCELLED = "action_cancelled"  # 用户取消

    # 系统事件
    SYSTEM_MESSAGE = "system_message"      # 系统消息
    WARNING = "warning"                    # 警告
    ERROR = "error"                        # 错误

    # 完成事件（终态事件：每个任务恰好发布一次，由 TaskSupervisor 保证）
    COMPLETED = "completed"                # 任务完成
    FAILED = "failed"                      # 任务失败
    CANCELLED = "cancelled"                # 任务取消

    # 统计事件
    STATS_UPDATE = "stats_update"          # 任务统计更新


class AgentEvent(BaseModel):
    """Agent事件"""

    event_type: AgentEventType = Field(..., description="事件类型")
    step_id: Optional[str] = Field(None, description="步骤ID")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="时间戳（aware UTC）")
    data: dict = Field(default_factory=dict, description="事件数据")
    seq: Optional[int] = Field(None, description="事件序号（由 TaskEventLog.publish 分配）")

    class Config:
        arbitrary_types_allowed = True

    def to_sse_format(self) -> str:
        """转换为SSE格式（标准三字段：id/event/data）"""
        from app.core.json_utils import jsonable

        def json_serializer(obj):
            """自定义 JSON 序列化器：date/datetime/Decimal 等统一走 jsonable"""
            return jsonable(obj)

        event_type = self.event_type.value if isinstance(self.event_type, AgentEventType) else self.event_type
        # 将step_id和timestamp包含在data中，以便前端使用
        data = {
            "event_type": event_type,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            **self.data
        }
        lines = []
        if self.seq is not None:
            lines.append(f"id: {self.seq}")
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data, ensure_ascii=False, default=json_serializer)}")
        return "\n".join(lines) + "\n\n"

    def to_dict(self) -> dict:
        """转换为字典"""
        return self.model_dump()
