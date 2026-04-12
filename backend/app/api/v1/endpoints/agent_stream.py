"""
流式Agent API端点

提供SSE(Server-Sent Events)格式的流式输出，实时展示Agent执行过程。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio
import logging

from app.agent.core.stream import AgentEvent, AgentEventType
from app.agent.agents.general_agent import create_general_agent
from app.db.postgres import async_session
from app.models.document import Message
from sqlalchemy import select


logger = logging.getLogger(__name__)

router = APIRouter()


class AgentStreamRequest(BaseModel):
    """流式Agent请求"""
    message: str = Field(..., description="用户消息")
    file_ids: List[str] = Field(default_factory=list, description="源文档ID列表")
    template_id: Optional[str] = Field(None, description="模板文档ID")
    conversation_id: Optional[str] = Field(None, description="对话ID")
    task_type: str = Field("auto", description="任务类型: auto/fill_table/query/operation")


@router.post("/stream")
async def agent_stream(request: AgentStreamRequest):
    """
    流式Agent对话接口

    使用SSE(Server-Sent Events)格式实时推送Agent执行过程。

    事件类型：
    - thinking_start/thinking_chunk/thinking_end: 思考过程
    - tool_call/tool_result/tool_error: 工具调用
    - step_start/step_progress/step_end: 步骤执行
    - data_retrieval_start/progress/end: 数据检索
    - fill_table_start/progress/end: 填表进度
    - completed/failed: 任务完成或失败
    """
    logger.info("=" * 70)
    logger.info("[API /agent/stream] 收到流式Agent请求")
    logger.info(f"[API /agent/stream] 消息: {request.message[:100]}..." if len(request.message) > 100 else f"[API /agent/stream] 消息: {request.message}")
    logger.info(f"[API /agent/stream] 文件数: {len(request.file_ids)} | 文件IDs: {request.file_ids}")
    logger.info(f"[API /agent/stream] 模板ID: {request.template_id}")
    logger.info(f"[API /agent/stream] 任务类型: {request.task_type}")
    logger.info(f"[API /agent/stream] 对话ID: {request.conversation_id}")

    # 加载对话历史
    conversation_history = []
    if request.conversation_id:
        try:
            async with async_session() as db:
                msg_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == request.conversation_id)
                    .order_by(Message.created_at.asc())
                    .limit(20)  # 最近20条消息
                )
                messages = msg_result.scalars().all()
                for msg in messages:
                    if msg.role in ("user", "assistant") and msg.content:
                        conversation_history.append({
                            "role": msg.role,
                            "content": msg.content
                        })
                logger.info(f"[API /agent/stream] 加载了 {len(conversation_history)} 条历史消息")
        except Exception as e:
            logger.warning(f"[API /agent/stream] 加载对话历史失败: {e}")

    async def event_generator():
        event_count = 0
        try:
            # 统一使用增强后的通用AgentRuntime处理所有任务
            logger.info("[API /agent/stream] 使用通用AgentRuntime")

            # 用于存储StreamManager的容器
            stream_manager_holder = {"stream": None}

            def on_stream_created(stream):
                stream_manager_holder["stream"] = stream

            def get_stream_manager():
                return stream_manager_holder["stream"]

            agent = create_general_agent(stream_manager_provider=get_stream_manager)

            async for event in agent.run_stream(
                message=request.message,
                file_ids=request.file_ids,
                template_id=request.template_id,
                conversation_history=conversation_history,
                on_stream_created=on_stream_created
            ):
                event_count += 1
                yield event

            logger.info(f"[API /agent/stream] 流结束 | 共发送 {event_count} 个事件")

        except asyncio.CancelledError:
            # 客户端断开连接
            logger.info(f"[API /agent/stream] 客户端断开连接 | 已发送 {event_count} 个事件")
            # 关闭StreamManager，通知后端停止生产事件
            sm = stream_manager_holder.get("stream")
            if sm and not sm.is_closed():
                await sm.cancel()
            raise  # 重新抛出，让FastAPI处理连接关闭

        except Exception as e:
            logger.exception(f"[API /agent/stream] 流式Agent执行失败: {e}")
            error_event = AgentEvent(
                event_type=AgentEventType.FAILED,
                data={"error": str(e)}
            )
            yield error_event.to_sse_format()

    logger.info("[API /agent/stream] 开始返回StreamingResponse")
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用Nginx缓冲
        }
    )


@router.post("/stream/fill-table")
async def fill_table_stream(request: AgentStreamRequest):
    """
    填表专用流式接口

    使用增强后的AgentRuntime处理填表任务。
    """
    logger.info("=" * 70)
    logger.info("[API /agent/stream/fill-table] 收到填表流式请求")
    logger.info(f"[API /agent/stream/fill-table] 消息: {request.message[:100]}..." if len(request.message) > 100 else f"[API /agent/stream/fill-table] 消息: {request.message}")
    logger.info(f"[API /agent/stream/fill-table] 文件数: {len(request.file_ids)} | 模板ID: {request.template_id}")

    if not request.template_id:
        logger.error("[API /agent/stream/fill-table] 缺少template_id")
        raise HTTPException(status_code=400, detail="填表任务需要提供template_id")

    # 加载对话历史
    conversation_history = []
    if request.conversation_id:
        try:
            async with async_session() as db:
                msg_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == request.conversation_id)
                    .order_by(Message.created_at.asc())
                    .limit(20)
                )
                messages_db = msg_result.scalars().all()
                for msg in messages_db:
                    if msg.role in ("user", "assistant") and msg.content:
                        conversation_history.append({
                            "role": msg.role,
                            "content": msg.content
                        })
                logger.info(f"[API /agent/stream/fill-table] 加载了 {len(conversation_history)} 条历史消息")
        except Exception as e:
            logger.warning(f"[API /agent/stream/fill-table] 加载对话历史失败: {e}")

    async def event_generator():
        event_count = 0
        try:
            # 使用增强后的通用AgentRuntime
            stream_manager_holder = {"stream": None}

            def on_stream_created(stream):
                stream_manager_holder["stream"] = stream

            def get_stream_manager():
                return stream_manager_holder["stream"]

            agent = create_general_agent(stream_manager_provider=get_stream_manager)

            async for event in agent.run_stream(
                message=request.message,
                file_ids=request.file_ids,
                template_id=request.template_id,
                conversation_history=conversation_history,
                on_stream_created=on_stream_created
            ):
                event_count += 1
                yield event

            logger.info(f"[API /agent/stream/fill-table] 流结束 | 共发送 {event_count} 个事件")

        except asyncio.CancelledError:
            # 客户端断开连接
            logger.info(f"[API /agent/stream/fill-table] 客户端断开连接 | 已发送 {event_count} 个事件")
            sm = stream_manager_holder.get("stream")
            if sm and not sm.is_closed():
                await sm.cancel()
            raise

        except Exception as e:
            logger.exception(f"[API /agent/stream/fill-table] 填表任务失败: {e}")
            error_event = AgentEvent(
                event_type=AgentEventType.FAILED,
                data={"error": str(e)}
            )
            yield error_event.to_sse_format()

    logger.info("[API /agent/stream/fill-table] 开始返回StreamingResponse")
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
