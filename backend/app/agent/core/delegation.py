"""
Agent委派核心模块

提供子Agent委派机制，将子Agent封装为BaseTool，使通用Agent可以通过
标准Function Calling机制调用子Agent。

核心组件：
- StreamBridge: 将子Agent的StreamManager事件转发到父Agent的StreamManager
- DelegateAgentTool: 子Agent委派工具基类
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from datetime import datetime

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.core.stream import StreamManager, AgentEvent, AgentEventType
from app.agent.core.tracker import StepTracker


logger = logging.getLogger(__name__)

# 委派Agent的显示名称映射
AGENT_DISPLAY_NAMES = {
    "delegate_fill_table": "填表Agent",
    "delegate_document_edit": "文档编辑Agent",
}


class StreamBridge:
    """流桥接器

    将子Agent的StreamManager事件桥接到父级StreamManager。
    子Agent的思考过程、工具调用等事件会以子步骤的形式
    传递给父级StreamManager，使前端能看到完整的执行过程。
    """

    def __init__(self, parent_stream: StreamManager, agent_name: str):
        self.parent_stream = parent_stream
        self.agent_name = agent_name
        self._bridge_task: Optional[asyncio.Task] = None

    def create_child_stream(self) -> StreamManager:
        """创建子Agent的StreamManager，并启动桥接协程"""
        child_stream = StreamManager()
        self._bridge_task = asyncio.create_task(self._bridge_events(child_stream))
        return child_stream

    async def _bridge_events(self, child_stream: StreamManager):
        """监听子StreamManager的队列，将事件转发到父StreamManager

        直接从队列消费 AgentEvent 对象（不使用 stream() 方法，因为 stream() yield 的是 SSE 字符串）。
        """
        try:
            event_count = 0
            while True:
                event = await asyncio.wait_for(
                    child_stream._event_queue.get(),
                    timeout=300.0
                )
                if event is None:  # 结束标记
                    break
                event_count += 1
                adapted = self._adapt_event(event)
                logger.info(f"[StreamBridge] 转发事件 #{event_count}: type={event.event_type}, step_id={adapted.step_id}")
                await self.parent_stream.emit(adapted)
            logger.info(f"[StreamBridge] 桥接完成，共转发 {event_count} 个事件")
        except asyncio.TimeoutError:
            logger.warning("[StreamBridge] 桥接超时")
        except Exception as e:
            logger.error(f"[StreamBridge] 桥接事件异常: {e}")

    def _adapt_event(self, event: AgentEvent) -> AgentEvent:
        """适配子Agent事件，标记来源为子Agent

        创建新的AgentEvent实例，不修改原始事件。
        """
        new_step_id = f"{self.agent_name}_{event.step_id}" if event.step_id else None
        new_data = {**event.data, "agent_name": self.agent_name}
        return AgentEvent(
            event_type=event.event_type,
            step_id=new_step_id,
            timestamp=event.timestamp,
            data=new_data,
        )

    async def wait_for_completion(self):
        """等待桥接任务完成"""
        if self._bridge_task:
            try:
                await self._bridge_task
            except Exception as e:
                logger.error(f"[StreamBridge] 等待桥接任务完成异常: {e}")


class DelegateAgentTool(BaseTool):
    """Agent委派工具基类

    将子Agent封装为一个BaseTool，使通用Agent的LLM可以通过
    Function Calling机制调用子Agent。

    子类需要实现:
    - name, description, parameters (标准BaseTool接口)
    - _create_agent() -> AgentRuntime: 创建子Agent实例
    """

    def __init__(self, parent_stream_provider=None):
        self.parent_stream_provider = parent_stream_provider

    @property
    def display_name(self) -> str:
        """获取显示名称"""
        return AGENT_DISPLAY_NAMES.get(self.name, self.name)

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行子Agent"""

        # 1. 创建独立的子Agent上下文（隔离）
        timestamp = datetime.utcnow().timestamp()

        # 将父级最近的对话历史传给子Agent，让子Agent了解上下文
        parent_history = context.conversation_history or []
        # 只取最近的几条，避免子Agent被过多无关历史干扰
        recent_history = parent_history[-6:] if len(parent_history) > 6 else parent_history

        child_context = ToolContext(
            session_id=f"{context.session_id}_{self.name}_{timestamp}",
            file_ids=params.get("file_ids", context.file_ids),
            template_id=params.get("template_id", context.template_id),
            conversation_history=recent_history,
            metadata={"parent_session_id": context.session_id},
        )

        # 2. 创建子Agent的流桥接
        parent_stream = self.parent_stream_provider() if self.parent_stream_provider else None
        bridge = None
        if parent_stream:
            bridge = StreamBridge(parent_stream, self.name)
            child_stream = bridge.create_child_stream()
        else:
            child_stream = StreamManager()

        # 3. 向父Stream发送委派开始事件
        delegation_step_id = f"{self.name}_delegation"
        if parent_stream:
            await parent_stream.emit(AgentEvent(
                event_type=AgentEventType.STEP_START,
                step_id=delegation_step_id,
                data={
                    "step_name": f"委派给{self.display_name}",
                    "description": params.get("task_description", ""),
                    "agent_name": self.name,
                    "is_delegation_start": True,
                }
            ))

        # 4. 创建并运行子Agent
        try:
            agent = self._create_agent()
            result = await agent.run(
                message=params.get("task_description", ""),
                file_ids=child_context.file_ids,
                template_id=child_context.template_id,
                conversation_history=recent_history,
                stream_manager=child_stream,
                step_tracker=StepTracker(),
            )

            # 5. 等待桥接任务完成
            if bridge:
                await bridge.wait_for_completion()

            # 6. 向父Stream发送委派结束事件
            if parent_stream:
                await parent_stream.emit(AgentEvent(
                    event_type=AgentEventType.STEP_END,
                    step_id=delegation_step_id,
                    data={
                        "message": "子Agent执行完成",
                        "agent_name": self.name,
                        "is_delegation_end": True,
                    }
                ))

            # 7. 将结果包装为ToolResult返回给通用Agent
            return ToolResult(
                success=result.get("success", False),
                data={
                    "agent_name": self.name,
                    "message": result.get("message", ""),
                    "steps_summary": result.get("steps", {}),
                    **self._extract_result(result),
                },
                error=result.get("error"),
            )
        except asyncio.TimeoutError:
            logger.error(f"[{self.__class__.__name__}] 子Agent执行超时")
            if not child_stream.is_closed():
                await child_stream.close()
            if bridge:
                await bridge.wait_for_completion()
            if parent_stream:
                await parent_stream.emit(AgentEvent(
                    event_type=AgentEventType.STEP_END,
                    step_id=delegation_step_id,
                    data={
                        "message": "子Agent执行超时",
                        "agent_name": self.name,
                        "is_delegation_end": True,
                    }
                ))
            return ToolResult(
                success=False,
                error="子Agent执行超时（300秒）",
            )
        except Exception as e:
            logger.exception(f"[{self.__class__.__name__}] 子Agent执行异常: {e}")
            if not child_stream.is_closed():
                await child_stream.close()
            if bridge:
                await bridge.wait_for_completion()
            if parent_stream:
                await parent_stream.emit(AgentEvent(
                    event_type=AgentEventType.STEP_END,
                    step_id=delegation_step_id,
                    data={
                        "message": f"子Agent执行异常: {str(e)}",
                        "agent_name": self.name,
                        "is_delegation_end": True,
                    }
                ))
            return ToolResult(
                success=False,
                error=f"子Agent执行异常: {str(e)}",
            )

    def _create_agent(self):
        """创建子Agent实例 - 子类实现"""
        raise NotImplementedError

    def _extract_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从子Agent结果中提取特有信息 - 子类可覆盖"""
        return {}
