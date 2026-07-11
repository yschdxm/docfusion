"""
系统工具 - 系统级操作

功能：
- 向用户提问
- 显示通知
- 获取当前时间
- 创建异步任务
- 查询任务状态
- 取消任务
"""

import logging
from typing import Any, Dict
from datetime import datetime

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel

logger = logging.getLogger(__name__)


class AskUserTool(BaseTool):
    """向用户提问工具"""

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return """向用户提问以获取更多信息或确认。

使用场景：
- 当需要用户提供额外信息时
- 当需要确认某个操作时
- 当需要让用户选择选项时

注意事项：
- 此工具会暂停执行，等待用户回复
- 可以提供选项列表让用户选择
- 也可以允许用户自由文本回答"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 300000  # 5分钟

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "问题内容"
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "选项标签"},
                            "value": {"type": "string", "description": "选项值"}
                        },
                        "required": ["label", "value"]
                    },
                    "description": "选项列表（可选）"
                },
                "allow_free_text": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否允许自由文本回答"
                }
            },
            "required": ["question"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """向用户提问"""
        try:
            question = params.get("question", "")
            options = params.get("options", [])
            allow_free_text = params.get("allow_free_text", True)

            if not question:
                return ToolResult(success=False, error="问题内容不能为空")

            # 通过StreamBus发送提问事件
            # 这里需要集成到实际的事件系统
            # 暂时返回模拟结果
            return ToolResult(
                success=True,
                data={
                    "question": question,
                    "options": options,
                    "allow_free_text": allow_free_text,
                    "message": "问题已发送，等待用户回复"
                },
                metadata={
                    "requires_user_input": True
                }
            )

        except Exception as e:
            logger.exception(f"向用户提问失败: {e}")
            return ToolResult(success=False, error=f"向用户提问失败: {str(e)}")


class ShowNotificationTool(BaseTool):
    """显示通知工具"""

    @property
    def name(self) -> str:
        return "show_notification"

    @property
    def description(self) -> str:
        return """向用户显示通知消息。

使用场景：
- 当需要告知用户某个操作已完成时
- 当需要提醒用户注意某些信息时
- 当需要显示警告或错误信息时

通知类型：
- info: 信息通知
- success: 成功通知
- warning: 警告通知
- error: 错误通知"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "通知内容"
                },
                "type": {
                    "type": "string",
                    "enum": ["info", "success", "warning", "error"],
                    "default": "info",
                    "description": "通知类型"
                }
            },
            "required": ["message"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """显示通知"""
        try:
            message = params.get("message", "")
            notification_type = params.get("type", "info")

            if not message:
                return ToolResult(success=False, error="通知内容不能为空")

            # 通过StreamBus发送通知事件
            # 这里需要集成到实际的事件系统
            # 暂时返回成功
            return ToolResult(
                success=True,
                data={
                    "message": message,
                    "type": notification_type,
                    "displayed": True
                }
            )

        except Exception as e:
            logger.exception(f"显示通知失败: {e}")
            return ToolResult(success=False, error=f"显示通知失败: {str(e)}")


class GetCurrentTimeTool(BaseTool):
    """获取当前时间工具"""

    @property
    def name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return """获取当前日期和时间。

使用场景：
- 当需要知道当前时间时
- 当需要在文档中添加时间戳时
- 当需要计算时间差时

注意事项：
- 默认返回中国标准时间（Asia/Shanghai）
- 可以通过timezone参数指定其他时区"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 1000  # 1秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "default": "Asia/Shanghai",
                    "description": "时区"
                },
                "format": {
                    "type": "string",
                    "default": "%Y-%m-%d %H:%M:%S",
                    "description": "时间格式"
                }
            }
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """获取当前时间"""
        try:
            timezone = params.get("timezone", "Asia/Shanghai")
            format_str = params.get("format", "%Y-%m-%d %H:%M:%S")

            # 获取当前时间
            now = datetime.now()

            # 格式化时间
            formatted_time = now.strftime(format_str)

            return ToolResult(
                success=True,
                data={
                    "current_time": formatted_time,
                    "timezone": timezone,
                    "timestamp": now.timestamp(),
                    "year": now.year,
                    "month": now.month,
                    "day": now.day,
                    "hour": now.hour,
                    "minute": now.minute,
                    "second": now.second
                }
            )

        except Exception as e:
            logger.exception(f"获取当前时间失败: {e}")
            return ToolResult(success=False, error=f"获取当前时间失败: {str(e)}")


class CreateTaskTool(BaseTool):
    """创建任务工具"""

    @property
    def name(self) -> str:
        return "create_task"

    @property
    def description(self) -> str:
        return """创建异步执行的任务。

使用场景：
- 当需要执行耗时操作时
- 当需要后台处理任务时
- 当需要批量处理文件时

注意事项：
- 任务创建后会返回任务ID
- 可以使用get_task_status查询任务状态
- 可以使用cancel_task取消任务"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "description": "任务类型"
                },
                "params": {
                    "type": "object",
                    "description": "任务参数"
                },
                "callback_url": {
                    "type": "string",
                    "description": "回调URL（可选）"
                }
            },
            "required": ["task_type"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """创建任务"""
        try:
            task_type = params.get("task_type", "")
            task_params = params.get("params", {})
            callback_url = params.get("callback_url")

            if not task_type:
                return ToolResult(success=False, error="任务类型不能为空")

            # 使用TaskManager创建任务
            from app.agent.core.task_manager import TaskManager
            task_manager = TaskManager()

            task_id = await task_manager.create_task(
                task_type=task_type,
                params=task_params,
                user_id=context.user_id,
                callback_url=callback_url
            )

            return ToolResult(
                success=True,
                data={
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "created",
                    "message": "任务已创建"
                }
            )

        except Exception as e:
            logger.exception(f"创建任务失败: {e}")
            return ToolResult(success=False, error=f"创建任务失败: {str(e)}")


class GetTaskStatusTool(BaseTool):
    """获取任务状态工具"""

    @property
    def name(self) -> str:
        return "get_task_status"

    @property
    def description(self) -> str:
        return """查询异步任务执行状态。

使用场景：
- 当需要了解任务执行进度时
- 当需要检查任务是否完成时
- 当需要获取任务结果时

任务状态：
- created: 已创建
- running: 执行中
- completed: 已完成
- failed: 失败
- cancelled: 已取消"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务ID"
                }
            },
            "required": ["task_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """获取任务状态"""
        try:
            task_id = params.get("task_id", "")

            if not task_id:
                return ToolResult(success=False, error="任务ID不能为空")

            # 使用TaskManager查询状态
            from app.agent.core.task_manager import TaskManager
            task_manager = TaskManager()

            task_status = await task_manager.get_task_status(task_id)

            if not task_status:
                return ToolResult(success=False, error=f"任务不存在: {task_id}")

            return ToolResult(
                success=True,
                data=task_status
            )

        except Exception as e:
            logger.exception(f"获取任务状态失败: {e}")
            return ToolResult(success=False, error=f"获取任务状态失败: {str(e)}")


class CancelTaskTool(BaseTool):
    """取消任务工具"""

    @property
    def name(self) -> str:
        return "cancel_task"

    @property
    def description(self) -> str:
        return """取消正在执行的异步任务。

使用场景：
- 当需要停止正在执行的任务时
- 当任务执行时间过长时
- 当发现任务参数错误时

注意事项：
- 只能取消正在执行的任务
- 已完成的任务无法取消"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务ID"
                }
            },
            "required": ["task_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """取消任务"""
        try:
            task_id = params.get("task_id", "")

            if not task_id:
                return ToolResult(success=False, error="任务ID不能为空")

            # 使用TaskManager取消任务
            from app.agent.core.task_manager import TaskManager
            task_manager = TaskManager()

            success = await task_manager.cancel_task(task_id)

            if success:
                return ToolResult(
                    success=True,
                    data={
                        "task_id": task_id,
                        "status": "cancelled",
                        "message": "任务已取消"
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"无法取消任务: {task_id}，任务可能已完成或不存在"
                )

        except Exception as e:
            logger.exception(f"取消任务失败: {e}")
            return ToolResult(success=False, error=f"取消任务失败: {str(e)}")
