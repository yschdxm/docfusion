"""
PlannerAgent - 路由和规划Agent

职责：
- 理解用户意图
- 制定执行计划
- 路由到专业Agent
"""

from typing import Dict, Any, List
import logging

from app.agent.core.orchestrator import AgentOrchestrator, DelegationTask
from app.agent.base.tool import ToolContext

logger = logging.getLogger(__name__)


PLANNER_SYSTEM_PROMPT = """你是一个智能文档处理助手的规划者。

## 职责
1. 理解用户意图
2. 制定执行计划
3. 路由到专业Agent

## 可用的专业Agent
- editor: 文档内容读取、编辑、格式调整、转换
- data: 数据查询、提取、统计分析
- knowledge: 知识图谱查询、构建、实体关系分析
- table: 模板表格结构分析、数据填写
- search: 跨文档搜索、RAG检索、信息定位

## 规划原则
1. 简单查询：直接回答
2. 复杂任务：先制定计划，再执行
3. 多领域任务：拆分为子任务，并行执行
4. 不确定时：先询问用户

## 输出格式
请返回JSON格式的执行计划：
{
    "intent": "用户意图描述",
    "agent": "目标Agent类型",
    "tasks": [
        {
            "description": "任务描述",
            "agent": "执行Agent",
            "priority": 优先级
        }
    ]
}
"""


class PlannerAgent:
    """PlannerAgent - 路由和规划Agent"""

    def __init__(self, orchestrator: AgentOrchestrator):
        """初始化PlannerAgent

        Args:
            orchestrator: Agent编排器
        """
        self.orchestrator = orchestrator

    async def plan(
        self,
        user_message: str,
        context: ToolContext
    ) -> Dict[str, Any]:
        """制定执行计划

        Args:
            user_message: 用户消息
            context: 工具上下文

        Returns:
            执行计划
        """
        # 使用LLM分析意图
        from app.services.llm_service import llm_service

        prompt = f"""{PLANNER_SYSTEM_PROMPT}

用户消息：{user_message}

请分析用户意图，制定执行计划。"""

        try:
            response = await llm_service.generate(
                prompt=prompt,
                max_tokens=500,
                temperature=0
            )

            # 解析响应
            import json
            plan = json.loads(response)

            return plan

        except Exception as e:
            logger.error(f"规划失败: {e}")
            # 默认使用editor
            return {
                "intent": "未知意图",
                "agent": "editor",
                "tasks": []
            }
