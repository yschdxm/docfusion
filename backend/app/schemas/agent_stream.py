"""
Agent流式API的Schema定义

定义流式请求和响应的数据模型
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class AgentStreamRequest(BaseModel):
    """流式Agent请求"""
    message: str = Field(..., description="用户消息")
    file_ids: List[str] = Field(default_factory=list, description="源文档ID列表")
    template_id: Optional[str] = Field(None, description="模板文档ID")
    conversation_id: Optional[str] = Field(None, description="对话ID(可选，用于继续已有对话)")
    task_type: str = Field("auto", description="任务类型: auto/fill_table/query/operation")


class AgentStreamResponse(BaseModel):
    """流式Agent响应（单个事件）"""
    event_type: str = Field(..., description="事件类型")
    step_id: Optional[str] = Field(None, description="步骤ID")
    timestamp: str = Field(..., description="时间戳")
    data: Dict[str, Any] = Field(default_factory=dict, description="事件数据")


class StepInfo(BaseModel):
    """步骤信息"""
    id: str = Field(..., description="步骤ID")
    type: str = Field(..., description="步骤类型")
    name: str = Field(..., description="步骤名称")
    description: str = Field("", description="步骤描述")
    status: str = Field("pending", description="步骤状态")
    progress: float = Field(0.0, description="进度百分比")
    tool_name: Optional[str] = Field(None, description="工具名称")
    tool_params: Optional[Dict[str, Any]] = Field(None, description="工具参数")
    tool_result: Optional[Dict[str, Any]] = Field(None, description="工具结果")
    thinking_content: Optional[str] = Field(None, description="思考内容")
    error_message: Optional[str] = Field(None, description="错误信息")


class AgentExecutionResult(BaseModel):
    """Agent执行结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field("", description="结果消息")
    error: Optional[str] = Field(None, description="错误信息")
    steps: List[StepInfo] = Field(default_factory=list, description="执行步骤")
    output_file_id: Optional[str] = Field(None, description="输出文件ID")
    download_url: Optional[str] = Field(None, description="下载链接")
