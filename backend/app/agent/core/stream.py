"""
流管理器 - 管理Agent的流式输出

参考OpenClaw的事件系统，支持：
- SSE (Server-Sent Events) 输出
- 多种事件类型 (思考、工具调用、进度、完成等)
- 事件序列化和推送
"""

import json
import asyncio
from typing import AsyncGenerator, Optional
from datetime import datetime
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

    # 完成事件
    COMPLETED = "completed"                # 任务完成
    FAILED = "failed"                      # 任务失败
    CANCELLED = "cancelled"                # 任务取消


class AgentEvent(BaseModel):
    """Agent事件"""

    event_type: AgentEventType = Field(..., description="事件类型")
    step_id: Optional[str] = Field(None, description="步骤ID")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="时间戳")
    data: dict = Field(default_factory=dict, description="事件数据")

    class Config:
        arbitrary_types_allowed = True

    def to_sse_format(self) -> str:
        """转换为SSE格式"""
        # 将step_id和timestamp包含在data中，以便前端使用
        data = {
            "event_type": self.event_type.value if isinstance(self.event_type, AgentEventType) else self.event_type,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            **self.data
        }
        return f"event: {self.event_type.value if isinstance(self.event_type, AgentEventType) else self.event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def to_dict(self) -> dict:
        """转换为字典"""
        return self.model_dump()


class StreamManager:
    """流管理器

    管理Agent的流式输出，支持SSE格式。
    """

    def __init__(self):
        self._event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._is_closed = False
        self._is_cancelled = False
        self._current_step_id: Optional[str] = None

    async def emit(self, event: AgentEvent) -> None:
        """发送一个事件"""
        if self._is_closed:
            logger.warning(f"[StreamManager] 尝试向已关闭的流发送事件: {event.event_type}")
            return

        await self._event_queue.put(event)
        logger.debug(f"[StreamManager] 发送事件: {event.event_type} | step_id={event.step_id}")

        # 记录重要事件到INFO级别
        if event.event_type in [AgentEventType.COMPLETED, AgentEventType.FAILED, AgentEventType.ERROR]:
            logger.info(f"[StreamManager] 重要事件: {event.event_type}")
        elif event.event_type in [AgentEventType.TOOL_CALL, AgentEventType.TOOL_RESULT, AgentEventType.TOOL_ERROR]:
            tool_name = event.data.get('tool_name', 'unknown')
            logger.info(f"[StreamManager] 工具事件: {event.event_type} | tool={tool_name}")

    async def emit_thinking_start(self, step_id: str, message: str = "") -> None:
        """发送思考开始事件"""
        self._current_step_id = step_id
        await self.emit(AgentEvent(
            event_type=AgentEventType.THINKING_START,
            step_id=step_id,
            data={"message": message}
        ))

    async def emit_thinking_chunk(self, content: str, is_complete: bool = False) -> None:
        """发送思考内容片段"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.THINKING_CHUNK,
            step_id=self._current_step_id,
            data={"content": content, "is_complete": is_complete}
        ))

    async def emit_thinking_end(self, summary: str = "") -> None:
        """发送思考结束事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.THINKING_END,
            step_id=self._current_step_id,
            data={"summary": summary}
        ))

    async def emit_tool_call(self, tool_name: str, parameters: dict) -> None:
        """发送工具调用事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.TOOL_CALL,
            step_id=self._current_step_id,
            data={"tool_name": tool_name, "parameters": parameters}
        ))

    async def emit_tool_result(self, tool_name: str, result: dict, execution_time_ms: int = 0) -> None:
        """发送工具结果事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.TOOL_RESULT,
            step_id=self._current_step_id,
            data={
                "tool_name": tool_name,
                "result": result,
                "execution_time_ms": execution_time_ms
            }
        ))

    async def emit_tool_error(self, tool_name: str, error: str) -> None:
        """发送工具错误事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.TOOL_ERROR,
            step_id=self._current_step_id,
            data={"tool_name": tool_name, "error": error}
        ))

    async def emit_step_start(self, step_id: str, step_name: str, description: str = "") -> None:
        """发送步骤开始事件"""
        self._current_step_id = step_id
        await self.emit(AgentEvent(
            event_type=AgentEventType.STEP_START,
            step_id=step_id,
            data={"step_name": step_name, "description": description}
        ))

    async def emit_step_progress(self, progress: float, message: str = "") -> None:
        """发送步骤进度事件

        Args:
            progress: 进度百分比 (0-100)
            message: 进度描述
        """
        await self.emit(AgentEvent(
            event_type=AgentEventType.STEP_PROGRESS,
            step_id=self._current_step_id,
            data={"progress": progress, "message": message}
        ))

    async def emit_step_end(self, step_id: str, result_summary: str = "") -> None:
        """发送步骤结束事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.STEP_END,
            step_id=step_id,
            data={"result_summary": result_summary}
        ))

    async def emit_data_retrieval_start(self, source: str, query: str) -> None:
        """发送数据检索开始事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.DATA_RETRIEVAL_START,
            step_id=self._current_step_id,
            data={"source": source, "query": query}
        ))

    async def emit_data_retrieval_progress(self, source: str, records_found: int, message: str = "") -> None:
        """发送数据检索进度事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.DATA_RETRIEVAL_PROGRESS,
            step_id=self._current_step_id,
            data={"source": source, "records_found": records_found, "message": message}
        ))

    async def emit_data_retrieval_end(self, source: str, total_records: int, success: bool = True) -> None:
        """发送数据检索结束事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.DATA_RETRIEVAL_END,
            step_id=self._current_step_id,
            data={"source": source, "total_records": total_records, "success": success}
        ))

    async def emit_fill_table_start(self, template_id: str, row_count: int = 0) -> None:
        """发送填表开始事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.FILL_TABLE_START,
            step_id=self._current_step_id,
            data={"template_id": template_id, "row_count": row_count}
        ))

    async def emit_fill_table_progress(self, filled_rows: int, total_rows: int, message: str = "") -> None:
        """发送填表进度事件"""
        progress = (filled_rows / total_rows * 100) if total_rows > 0 else 0
        await self.emit(AgentEvent(
            event_type=AgentEventType.FILL_TABLE_PROGRESS,
            step_id=self._current_step_id,
            data={
                "filled_rows": filled_rows,
                "total_rows": total_rows,
                "progress": round(progress, 1),
                "message": message
            }
        ))

    async def emit_fill_table_end(self, filled_file_id: str, download_url: str = "") -> None:
        """发送填表结束事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.FILL_TABLE_END,
            step_id=self._current_step_id,
            data={"filled_file_id": filled_file_id, "download_url": download_url}
        ))

    async def emit_content_chunk(self, content: str) -> None:
        """发送回复内容片段事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.CONTENT_CHUNK,
            step_id=self._current_step_id,
            data={"content": content}
        ))

    async def emit_content_end(self) -> None:
        """发送回复内容结束事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.CONTENT_END,
            step_id=self._current_step_id,
            data={}
        ))

    async def emit_assistant_message(self, message: str) -> None:
        """发送AI助手完整消息（用于中间步骤的回复）"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.ASSISTANT_MESSAGE,
            step_id=None,
            data={"message": message}
        ))

    async def emit_action_required(self, action_type: str, action_data: dict, message: str = "") -> None:
        """发送需要用户操作事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.ACTION_REQUIRED,
            step_id=self._current_step_id,
            data={"action_type": action_type, "action_data": action_data, "message": message}
        ))

    async def emit_system_message(self, message: str, level: str = "info") -> None:
        """发送系统消息事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.SYSTEM_MESSAGE,
            step_id=self._current_step_id,
            data={"message": message, "level": level}
        ))

    async def emit_warning(self, message: str) -> None:
        """发送警告事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.WARNING,
            step_id=self._current_step_id,
            data={"message": message}
        ))

    async def emit_error(self, error: str, details: dict = None) -> None:
        """发送错误事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.ERROR,
            step_id=self._current_step_id,
            data={"error": error, "details": details or {}}
        ))

    async def emit_completed(self, message: str, result_data: dict = None) -> None:
        """发送任务完成事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.COMPLETED,
            step_id=self._current_step_id,
            data={"message": message, "result": result_data or {}}
        ))
        await self.close()

    async def emit_failed(self, error: str, details: dict = None) -> None:
        """发送任务失败事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.FAILED,
            step_id=self._current_step_id,
            data={"error": error, "details": details or {}}
        ))
        await self.close()

    async def emit_cancelled(self, message: str = "任务已取消") -> None:
        """发送任务取消事件"""
        await self.emit(AgentEvent(
            event_type=AgentEventType.CANCELLED,
            step_id=self._current_step_id,
            data={"message": message}
        ))
        await self.close()

    async def close(self) -> None:
        """关闭流"""
        if not self._is_closed:
            self._is_closed = True
            logger.info(f"[StreamManager] 流已关闭 | 总事件数: {self._event_queue.qsize()}")
            # 发送结束标记
            await self._event_queue.put(None)

    async def stream(self) -> AsyncGenerator[str, None]:
        """生成SSE流

        Yields:
            SSE格式的字符串
        """
        event_count = 0
        logger.info("[StreamManager] SSE流开始")

        while True:
            try:
                # 使用timeout避免永久阻塞
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=600.0  # 10分钟超时
                )

                if event is None:  # 结束标记
                    logger.info(f"[StreamManager] SSE流结束 | 共发送 {event_count} 个事件")
                    break

                event_count += 1
                sse_data = event.to_sse_format()

                # 每10个事件记录一次日志
                if event_count % 10 == 0:
                    logger.info(f"[StreamManager] 已发送 {event_count} 个事件")

                yield sse_data

            except asyncio.TimeoutError:
                logger.warning("[StreamManager] 流超时，关闭连接")
                break
            except Exception as e:
                logger.error(f"[StreamManager] 流异常: {e}")
                break

    def is_closed(self) -> bool:
        """检查流是否已关闭"""
        return self._is_closed

    def is_cancelled(self) -> bool:
        """检查是否被取消（客户端断开）"""
        return self._is_cancelled

    async def cancel(self) -> None:
        """标记为已取消（客户端断开时调用）"""
        self._is_cancelled = True
        logger.info("[StreamManager] 流已被标记为取消")
        await self.close()
