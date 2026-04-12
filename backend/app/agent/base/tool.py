"""
工具基类定义 - 参考OpenClaw的Tool系统

每个工具必须实现BaseTool接口，定义:
- name: 工具名称，LLM通过这个名称调用
- description: 工具描述，告诉LLM这个工具是做什么的
- parameters: 参数schema (JSON Schema格式)
- execute: 执行工具的方法
"""

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field

# UUID格式校验正则
_UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


class ToolContext(BaseModel):
    """工具执行上下文"""
    session_id: str = Field(..., description="会话ID")
    user_id: Optional[str] = Field(None, description="用户ID")
    file_ids: list[str] = Field(default_factory=list, description="选中的源文档ID列表")
    template_id: Optional[str] = Field(None, description="模板文档ID")
    conversation_history: list[Dict[str, str]] = Field(default_factory=list, description="对话历史")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")

    class Config:
        arbitrary_types_allowed = True


class ToolResult(BaseModel):
    """工具执行结果"""
    success: bool = Field(..., description="是否成功")
    data: Any = Field(None, description="返回数据")
    error: Optional[str] = Field(None, description="错误信息")
    execution_time_ms: int = Field(0, description="执行时间(毫秒)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")

    class Config:
        arbitrary_types_allowed = True


class BaseTool(ABC):
    """工具基类

    所有工具必须继承此类并实现以下方法:
    - name: 返回工具名称
    - description: 返回工具描述
    - parameters: 返回参数schema (JSON Schema格式)
    - execute: 执行工具

    示例:
        class MyTool(BaseTool):
            @property
            def name(self) -> str:
                return "my_tool"

            @property
            def description(self) -> str:
                return "这是一个示例工具"

            @property
            def parameters(self) -> Dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string", "description": "参数1"}
                    },
                    "required": ["param1"]
                }

            async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
                # 实现工具逻辑
                return ToolResult(success=True, data={"result": "success"})
    """

    @staticmethod
    def validate_uuid(value: Any, field_name: str) -> Optional[str]:
        """校验UUID格式，返回错误信息或None（表示校验通过）"""
        if not value:
            return f"缺少必需参数: {field_name}"
        if not _UUID_PATTERN.match(str(value)):
            return f"{field_name}格式不正确（期望UUID格式，如: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx），收到: '{value}'"
        return None

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，LLM通过这个名称调用工具"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，告诉LLM这个工具是做什么的"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """参数schema，JSON Schema格式

        示例:
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询"
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量"
                }
            },
            "required": ["query"]
        }
        """
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行工具

        Args:
            params: LLM传入的参数，已经过验证
            context: 工具执行上下文

        Returns:
            ToolResult: 执行结果
        """
        pass

    def to_function_schema(self) -> Dict[str, Any]:
        """转换为OpenAI Function Calling格式的schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

    def to_json(self) -> Dict[str, Any]:
        """转换为JSON格式，用于前端展示"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }

    async def run(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """运行工具（带错误处理和计时）"""
        start_time = datetime.utcnow()
        try:
            # 验证必需参数
            required = self.parameters.get("required", [])
            for param in required:
                if param not in params:
                    return ToolResult(
                        success=False,
                        error=f"缺少必需参数: {param}"
                    )

            # 执行工具
            result = await self.execute(params, context)

            # 计算执行时间
            end_time = datetime.utcnow()
            execution_time = int((end_time - start_time).total_seconds() * 1000)
            result.execution_time_ms = execution_time

            return result

        except Exception as e:
            end_time = datetime.utcnow()
            execution_time = int((end_time - start_time).total_seconds() * 1000)
            return ToolResult(
                success=False,
                error=f"工具执行错误: {str(e)}",
                execution_time_ms=execution_time
            )
