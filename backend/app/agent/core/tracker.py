"""
步骤追踪器 - 追踪Agent执行的每一步

功能：
- 记录每个步骤的详细信息
- 支持步骤回溯和恢复
- 提供执行历史查询
- 生成执行报告
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class StepStatus(str, Enum):
    """步骤状态"""
    PENDING = "pending"           # 待执行
    RUNNING = "running"           # 执行中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败
    SKIPPED = "skipped"           # 已跳过


class StepType(str, Enum):
    """步骤类型"""
    THINKING = "thinking"         # 思考
    TOOL_CALL = "tool_call"       # 工具调用
    DATA_RETRIEVAL = "data_retrieval"  # 数据检索
    FILL_TABLE = "fill_table"     # 填表
    VALIDATION = "validation"     # 验证
    CONFIRMATION = "confirmation" # 确认


class Step(BaseModel):
    """步骤记录"""

    id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}", description="步骤ID")
    type: StepType = Field(..., description="步骤类型")
    name: str = Field(..., description="步骤名称")
    description: str = Field("", description="步骤描述")
    status: StepStatus = Field(StepStatus.PENDING, description="步骤状态")

    # 时间戳
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="创建时间")
    started_at: Optional[str] = Field(None, description="开始时间")
    completed_at: Optional[str] = Field(None, description="完成时间")

    # 执行信息
    tool_name: Optional[str] = Field(None, description="工具名称(如果是工具调用)")
    tool_params: Optional[Dict[str, Any]] = Field(None, description="工具参数")
    tool_result: Optional[Dict[str, Any]] = Field(None, description="工具结果")
    error_message: Optional[str] = Field(None, description="错误信息")

    # 思考内容
    thinking_content: Optional[str] = Field(None, description="思考内容")

    # 进度
    progress: float = Field(0.0, description="进度百分比(0-100)")
    progress_message: str = Field("", description="进度描述")

    # 子步骤
    substeps: List["Step"] = Field(default_factory=list, description="子步骤")
    parent_id: Optional[str] = Field(None, description="父步骤ID")

    # 元数据
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")

    class Config:
        arbitrary_types_allowed = True

    def to_dict(self) -> dict:
        """转换为字典"""
        return self.model_dump()

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return self.model_dump_json()


class StepTracker:
    """步骤追踪器

    追踪Agent执行的完整流程，支持步骤管理和查询。
    """

    def __init__(self):
        self._steps: List[Step] = []
        self._current_step: Optional[Step] = None
        self._step_map: Dict[str, Step] = {}

    def create_step(
        self,
        step_type: StepType,
        name: str,
        description: str = "",
        parent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Step:
        """创建新步骤

        Args:
            step_type: 步骤类型
            name: 步骤名称
            description: 步骤描述
            parent_id: 父步骤ID
            tool_name: 工具名称
            tool_params: 工具参数
            metadata: 元数据

        Returns:
            创建的步骤
        """
        step = Step(
            type=step_type,
            name=name,
            description=description,
            parent_id=parent_id,
            tool_name=tool_name,
            tool_params=tool_params,
            metadata=metadata or {}
        )

        self._steps.append(step)
        self._step_map[step.id] = step

        # 如果有父步骤，添加到子步骤列表
        if parent_id and parent_id in self._step_map:
            self._step_map[parent_id].substeps.append(step)

        return step

    def start_step(self, step_id: str) -> Optional[Step]:
        """开始执行步骤

        Args:
            step_id: 步骤ID

        Returns:
            步骤对象或None
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = StepStatus.RUNNING
            step.started_at = datetime.utcnow().isoformat()
            self._current_step = step
        return step

    def complete_step(
        self,
        step_id: str,
        result: Optional[Dict[str, Any]] = None,
        thinking_content: Optional[str] = None
    ) -> Optional[Step]:
        """完成步骤

        Args:
            step_id: 步骤ID
            result: 结果数据
            thinking_content: 思考内容

        Returns:
            步骤对象或None
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.utcnow().isoformat()
            step.progress = 100.0
            step.progress_message = "已完成"

            if result:
                step.tool_result = result
            if thinking_content:
                step.thinking_content = thinking_content

        return step

    def fail_step(self, step_id: str, error_message: str) -> Optional[Step]:
        """标记步骤失败

        Args:
            step_id: 步骤ID
            error_message: 错误信息

        Returns:
            步骤对象或None
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = StepStatus.FAILED
            step.completed_at = datetime.utcnow().isoformat()
            step.error_message = error_message
        return step

    def skip_step(self, step_id: str, reason: str = "") -> Optional[Step]:
        """跳过步骤

        Args:
            step_id: 步骤ID
            reason: 跳过原因

        Returns:
            步骤对象或None
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = StepStatus.SKIPPED
            step.completed_at = datetime.utcnow().isoformat()
            step.metadata["skip_reason"] = reason
        return step

    def update_progress(self, step_id: str, progress: float, message: str = "") -> Optional[Step]:
        """更新步骤进度

        Args:
            step_id: 步骤ID
            progress: 进度百分比(0-100)
            message: 进度描述

        Returns:
            步骤对象或None
        """
        step = self._step_map.get(step_id)
        if step:
            step.progress = progress
            step.progress_message = message
        return step

    def update_thinking(self, step_id: str, content: str) -> Optional[Step]:
        """更新思考内容

        Args:
            step_id: 步骤ID
            content: 思考内容

        Returns:
            步骤对象或None
        """
        step = self._step_map.get(step_id)
        if step:
            if step.thinking_content:
                step.thinking_content += content
            else:
                step.thinking_content = content
        return step

    def get_step(self, step_id: str) -> Optional[Step]:
        """获取步骤

        Args:
            step_id: 步骤ID

        Returns:
            步骤对象或None
        """
        return self._step_map.get(step_id)

    def get_current_step(self) -> Optional[Step]:
        """获取当前步骤"""
        return self._current_step

    def get_all_steps(self) -> List[Step]:
        """获取所有步骤"""
        return self._steps.copy()

    def get_steps_by_type(self, step_type: StepType) -> List[Step]:
        """获取指定类型的步骤"""
        return [s for s in self._steps if s.type == step_type]

    def get_steps_by_status(self, status: StepStatus) -> List[Step]:
        """获取指定状态的步骤"""
        return [s for s in self._steps if s.status == status]

    def get_root_steps(self) -> List[Step]:
        """获取根步骤(没有父步骤)"""
        return [s for s in self._steps if s.parent_id is None]

    def get_execution_summary(self) -> Dict[str, Any]:
        """获取执行摘要

        Returns:
            执行摘要
        """
        total = len(self._steps)
        completed = len(self.get_steps_by_status(StepStatus.COMPLETED))
        failed = len(self.get_steps_by_status(StepStatus.FAILED))
        running = len(self.get_steps_by_status(StepStatus.RUNNING))
        pending = len(self.get_steps_by_status(StepStatus.PENDING))
        skipped = len(self.get_steps_by_status(StepStatus.SKIPPED))

        return {
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "skipped": skipped,
            "success_rate": round(completed / total * 100, 2) if total > 0 else 0
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "steps": [s.to_dict() for s in self._steps],
            "summary": self.get_execution_summary()
        }

    def clear(self) -> None:
        """清空所有步骤"""
        self._steps.clear()
        self._step_map.clear()
        self._current_step = None
