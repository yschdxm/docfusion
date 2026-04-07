"""
Agent系统模块

参考OpenClaw的Agent架构，专注于文档处理领域。

核心组件:
- BaseTool: 工具基类
- ToolRegistry: 工具注册表
- ToolExecutor: 工具执行器
- AgentRuntime: Agent运行时
- StreamManager: 流管理器
- StepTracker: 步骤追踪器

使用示例:
    from app.agent import AgentRuntime, ToolRegistry, BaseTool

    # 创建注册表
    registry = ToolRegistry()

    # 注册工具
    registry.register(MyTool())

    # 创建运行时
    runtime = AgentRuntime(registry)

    # 运行Agent
    result = await runtime.run(
        message="请帮我填写表格",
        file_ids=["doc1", "doc2"],
        template_id="template1"
    )
"""

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.agent.core.registry import ToolRegistry, tool_registry
from app.agent.core.executor import ToolExecutor
from app.agent.core.runtime import AgentRuntime
from app.agent.core.stream import StreamManager, AgentEventType, AgentEvent
from app.agent.core.tracker import StepTracker, Step, StepStatus, StepType

__all__ = [
    # 基础组件
    "BaseTool",
    "ToolContext",
    "ToolResult",

    # 核心组件
    "ToolRegistry",
    "tool_registry",
    "ToolExecutor",
    "AgentRuntime",
    "StreamManager",
    "AgentEventType",
    "AgentEvent",
    "StepTracker",
    "Step",
    "StepStatus",
    "StepType",
]
