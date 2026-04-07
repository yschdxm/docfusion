"""
流式Agent API端点

提供SSE(Server-Sent Events)格式的流式输出，实时展示Agent执行过程。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import logging

from app.agent.core.stream import AgentEvent, AgentEventType
from app.agent import AgentRuntime, ToolRegistry
from app.agent.tools import (
    RAGTool,
    DocReaderTool,
    PGQueryTool,
    Neo4jQueryTool,
    ListDocumentsTool,
    GetTableStructureTool,
    FillTableTool,
    ExtractFromDocsTool,
)


logger = logging.getLogger(__name__)

router = APIRouter()


class AgentStreamRequest(BaseModel):
    """流式Agent请求"""
    message: str = Field(..., description="用户消息")
    file_ids: List[str] = Field(default_factory=list, description="源文档ID列表")
    template_id: Optional[str] = Field(None, description="模板文档ID")
    conversation_id: Optional[str] = Field(None, description="对话ID")
    task_type: str = Field("auto", description="任务类型: auto/fill_table/query/operation")


def create_general_agent() -> AgentRuntime:
    """创建通用Agent（支持所有任务类型）"""
    registry = ToolRegistry()
    registry.register(RAGTool())
    registry.register(DocReaderTool())
    registry.register(PGQueryTool())
    registry.register(Neo4jQueryTool())
    registry.register(ListDocumentsTool())
    registry.register(GetTableStructureTool())
    registry.register(FillTableTool())
    registry.register(ExtractFromDocsTool())

    return AgentRuntime(registry, max_iterations=50)


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

    async def event_generator():
        event_count = 0
        try:
            # 统一使用增强后的通用AgentRuntime处理所有任务
            logger.info("[API /agent/stream] 使用通用AgentRuntime")
            agent = create_general_agent()

            async for event in agent.run_stream(
                message=request.message,
                file_ids=request.file_ids,
                template_id=request.template_id
            ):
                event_count += 1
                yield event

            logger.info(f"[API /agent/stream] 流结束 | 共发送 {event_count} 个事件")

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

    async def event_generator():
        event_count = 0
        try:
            # 使用增强后的通用AgentRuntime
            agent = create_general_agent()

            async for event in agent.run_stream(
                message=request.message,
                file_ids=request.file_ids,
                template_id=request.template_id
            ):
                event_count += 1
                yield event

            logger.info(f"[API /agent/stream/fill-table] 流结束 | 共发送 {event_count} 个事件")

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
