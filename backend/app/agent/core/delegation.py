"""
Agent委派核心模块

提供子Agent委派机制，将子Agent封装为BaseTool，使通用Agent可以通过
标准Function Calling机制调用子Agent。

核心组件：
- StreamBridge: 订阅子Agent的TaskEventLog，将事件转发到父级TaskEventLog
- DelegateAgentTool: 子Agent委派工具基类
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from datetime import datetime

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.core.stream import AgentEvent, AgentEventType
from app.agent.core.event_log import TaskEventLog
from app.agent.core.tracker import StepTracker


logger = logging.getLogger(__name__)

# 委派Agent的显示名称映射
AGENT_DISPLAY_NAMES = {
    "delegate_fill_table": "填表Agent",
    "delegate_document_edit": "文档编辑Agent",
}


class StreamBridge:
    """流桥接器

    订阅子Agent的TaskEventLog，将事件转发到父级TaskEventLog。
    子Agent的思考过程、工具调用等事件会以子步骤的形式
    传递给父级TaskEventLog，使前端能看到完整的执行过程。
    """

    def __init__(self, parent_log: TaskEventLog, agent_name: str):
        self.parent_log = parent_log
        self.agent_name = agent_name
        self._bridge_task: Optional[asyncio.Task] = None

    def start(self, child_log: TaskEventLog) -> None:
        """启动桥接协程（消费子日志事件并转发）"""
        self._bridge_task = asyncio.create_task(
            self._bridge_events(child_log),
            name=f"stream-bridge-{self.agent_name}",
        )

    async def _bridge_events(self, child_log: TaskEventLog):
        """订阅子日志，将事件转发到父日志（跳过心跳）"""
        try:
            event_count = 0
            async for item in child_log.subscribe(heartbeat=30.0):
                # 父日志已结束（如任务取消），停止转发
                if self.parent_log.is_finished:
                    logger.info(f"[StreamBridge] 父日志已结束，停止桥接 | 已转发 {event_count} 个事件")
                    break
                if item is None:  # 心跳不转发
                    continue
                event_count += 1
                adapted = self._adapt_event(item)
                logger.debug(f"[StreamBridge] 转发事件 #{event_count}: type={item.event_type}, step_id={adapted.step_id}")
                await self.parent_log.emit(adapted)
            logger.info(f"[StreamBridge] 桥接完成，共转发 {event_count} 个事件")
        except asyncio.CancelledError:
            logger.info(f"[StreamBridge] 桥接被取消 | agent={self.agent_name}")
            raise
        except Exception as e:
            logger.error(f"[StreamBridge] 桥接事件异常: {e}")

    def _adapt_event(self, event: AgentEvent) -> AgentEvent:
        """适配子Agent事件，标记来源为子Agent

        创建新的AgentEvent实例，不修改原始事件。
        注意：不带 seq，由父日志 publish 时重新分配。
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
            except asyncio.CancelledError:
                pass
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

        # 取消信号从父级传播（任务取消时子Agent一起退出）
        cancel_event = context.metadata.get("cancel_event")

        child_context = ToolContext(
            session_id=f"{context.session_id}_{self.name}_{timestamp}",
            user_id=context.user_id,
            file_ids=params.get("file_ids", context.file_ids),
            template_id=params.get("template_id", context.template_id),
            conversation_history=recent_history,
            metadata={
                "parent_session_id": context.session_id,
                "cancel_event": cancel_event,
                # run_id / conversation_id 透传，保证同一轮指令的版本化判定跨委派一致
                "run_id": context.metadata.get("run_id"),
                "conversation_id": context.metadata.get("conversation_id"),
            },
        )

        # 2. 创建子Agent的事件日志与流桥接
        parent_log = self.parent_stream_provider() if self.parent_stream_provider else None
        child_log = TaskEventLog()
        bridge = None
        if parent_log:
            bridge = StreamBridge(parent_log, self.name)
            bridge.start(child_log)

        # 3. 向父日志发送委派开始事件
        delegation_step_id = f"{self.name}_delegation"
        if parent_log:
            await parent_log.emit(AgentEvent(
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
                event_log=child_log,
                step_tracker=StepTracker(),
                user_id=child_context.user_id,
                cancel_event=cancel_event,
                conversation_id=context.metadata.get("conversation_id"),
                run_id=context.metadata.get("run_id"),
            )

            # 5. 收尾：关闭子日志并等待桥接完成
            await child_log.finish()
            if bridge:
                await bridge.wait_for_completion()

            # 6. 向父日志发送委派结束事件
            if parent_log:
                await parent_log.emit(AgentEvent(
                    event_type=AgentEventType.STEP_END,
                    step_id=delegation_step_id,
                    data={
                        "message": "子Agent执行完成",
                        "agent_name": self.name,
                        "is_delegation_end": True,
                    }
                ))

            # 7. 将结果包装为ToolResult返回给通用Agent
            #    收集子agent的token统计，供父agent汇总
            sub_usage = getattr(agent, 'accumulated_usage', None)
            return ToolResult(
                success=result.get("success", False),
                data={
                    "agent_name": self.name,
                    "message": result.get("message", ""),
                    "steps_summary": result.get("steps", {}),
                    "sub_agent_usage": sub_usage,
                    **self._extract_result(result),
                },
                error=result.get("error"),
            )
        except asyncio.CancelledError:
            logger.info(f"[{self.__class__.__name__}] 子Agent随任务一起取消")
            await child_log.finish()
            if bridge:
                await bridge.wait_for_completion()
            raise
        except Exception as e:
            logger.exception(f"[{self.__class__.__name__}] 子Agent执行异常: {e}")
            await child_log.finish()
            if bridge:
                await bridge.wait_for_completion()
            if parent_log:
                await parent_log.emit(AgentEvent(
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
