"""
上下文管理器 - 管理对话上下文

功能：
- Token预算管理
- 消息窗口管理
- 工具结果压缩
- 对话摘要生成
- 渐进式压缩策略
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Token 预算分配策略"""
    total_limit: int = 128000        # 模型上下文窗口
    system_prompt_reserve: int = 8000 # 系统提示词预留
    tool_schemas_reserve: int = 4000  # 工具 Schema 预留
    response_reserve: int = 8000      # 模型回复预留
    safety_margin: int = 4000         # 安全余量

    @property
    def available_for_messages(self) -> int:
        """可用于消息的 Token 数"""
        return (
            self.total_limit
            - self.system_prompt_reserve
            - self.tool_schemas_reserve
            - self.response_reserve
            - self.safety_margin
        )

    @property
    def usage_ratio(self) -> float:
        """当前使用率"""
        return self._usage_ratio if hasattr(self, '_usage_ratio') else 0.0

    @usage_ratio.setter
    def usage_ratio(self, value: float):
        self._usage_ratio = value


@dataclass
class Message:
    """消息"""
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResultCompressor:
    """工具结果压缩器"""

    def compress(self, content: str, target_tokens: int) -> str:
        """压缩内容到目标 Token 数

        简单实现：按字符数截断（假设1个中文字符≈2个token）

        Args:
            content: 原始内容
            target_tokens: 目标 Token 数

        Returns:
            压缩后的内容
        """
        # 估算当前 token 数（粗略）
        estimated_tokens = len(content) * 1.5

        if estimated_tokens <= target_tokens:
            return content

        # 计算需要保留的字符数
        target_chars = int(target_tokens / 1.5)

        # 保留开头和结尾
        head_chars = int(target_chars * 0.3)
        tail_chars = int(target_chars * 0.7)

        compressed = (
            content[:head_chars]
            + f"\n\n... (省略 {int(estimated_tokens - target_tokens)} tokens) ...\n\n"
            + content[-tail_chars:]
        )

        return compressed


class Summarizer:
    """对话摘要生成器"""

    def __init__(self, llm_service=None):
        self.llm_service = llm_service

    async def summarize(self, messages: List[Message]) -> str:
        """生成对话摘要

        简单实现：提取关键信息

        Args:
            messages: 消息列表

        Returns:
            摘要内容
        """
        if not messages:
            return ""

        # 提取用户和助手的关键消息
        summary_parts = []
        for msg in messages:
            if msg.role in ["user", "assistant"]:
                # 截取前100个字符
                preview = msg.content[:100]
                if len(msg.content) > 100:
                    preview += "..."
                summary_parts.append(f"[{msg.role}]: {preview}")

        return "\n".join(summary_parts[-10:])  # 只保留最近10条


class ContextManager:
    """上下文管理器

    负责管理对话上下文，包括Token预算、消息窗口、结果压缩、对话摘要。
    """

    def __init__(
        self,
        token_budget: Optional[TokenBudget] = None,
        compressor: Optional[ResultCompressor] = None,
        summarizer: Optional[Summarizer] = None
    ):
        """初始化上下文管理器

        Args:
            token_budget: Token预算配置
            compressor: 结果压缩器
            summarizer: 摘要生成器
        """
        self.token_budget = token_budget or TokenBudget()
        self.compressor = compressor or ResultCompressor()
        self.summarizer = summarizer or Summarizer()

        self._messages: List[Message] = []
        self._summary: Optional[str] = None

    def add_message(self, message: Message) -> None:
        """添加消息

        Args:
            message: 消息对象
        """
        self._messages.append(message)
        self._update_usage_ratio()

    def get_messages(self, max_tokens: Optional[int] = None) -> List[Message]:
        """获取消息列表

        Args:
            max_tokens: 最大 Token 数限制

        Returns:
            消息列表
        """
        if max_tokens is None:
            return self._messages.copy()

        # 从最新消息开始，累加 Token 数
        selected_messages = []
        total_tokens = 0

        for msg in reversed(self._messages):
            if total_tokens + msg.token_count > max_tokens:
                break
            selected_messages.insert(0, msg)
            total_tokens += msg.token_count

        return selected_messages

    def _update_usage_ratio(self) -> None:
        """更新 Token 使用率"""
        total_tokens = sum(msg.token_count for msg in self._messages)
        self.token_budget.usage_ratio = total_tokens / self.token_budget.available_for_messages

    def should_compress(self) -> bool:
        """是否需要压缩（60%阈值）"""
        return self.token_budget.usage_ratio > 0.6

    def should_summarize(self) -> bool:
        """是否需要摘要（75%阈值）"""
        return self.token_budget.usage_ratio > 0.75

    def should_aggressive_compress(self) -> bool:
        """是否需要激进压缩（85%阈值）"""
        return self.token_budget.usage_ratio > 0.85

    def should_force_compact(self) -> bool:
        """是否需要强制压缩（95%阈值）"""
        return self.token_budget.usage_ratio > 0.95

    def compress_tool_result(self, content: str) -> str:
        """压缩工具结果

        Args:
            content: 原始内容

        Returns:
            压缩后的内容
        """
        if not self.should_compress():
            return content

        # 计算目标 token 数
        target_tokens = int(self.token_budget.available_for_messages * 0.1)
        return self.compressor.compress(content, target_tokens)

    async def auto_compact(self) -> str:
        """自动压缩上下文

        Returns:
            摘要内容
        """
        if not self.should_summarize():
            return ""

        logger.info("执行自动压缩 | Token使用率: {:.1%}".format(self.token_budget.usage_ratio))

        # 生成摘要
        summary = await self.summarizer.summarize(self._messages)

        # 清空消息历史
        self._messages = []
        self._summary = summary

        # 重置使用率
        self.token_budget.usage_ratio = 0.0

        return summary

    def get_context_for_llm(self) -> Dict[str, Any]:
        """获取用于 LLM 调用的上下文

        Returns:
            包含消息和摘要的字典
        """
        messages = self.get_messages()

        # 如果有摘要，添加到消息开头
        if self._summary:
            messages.insert(0, Message(
                role="system",
                content=f"之前的对话摘要:\n{self._summary}",
                token_count=len(self._summary) * 2  # 估算
            ))

        return {
            "messages": messages,
            "token_budget": self.token_budget,
            "usage_ratio": self.token_budget.usage_ratio
        }

    def clear(self) -> None:
        """清空上下文"""
        self._messages = []
        self._summary = None
        self.token_budget.usage_ratio = 0.0
        logger.info("上下文已清空")

    def get_stats(self) -> Dict[str, Any]:
        """获取上下文统计信息

        Returns:
            统计信息字典
        """
        total_tokens = sum(msg.token_count for msg in self._messages)
        return {
            "message_count": len(self._messages),
            "total_tokens": total_tokens,
            "available_tokens": self.token_budget.available_for_messages,
            "usage_ratio": self.token_budget.usage_ratio,
            "has_summary": self._summary is not None
        }


# 全局上下文管理器实例
context_manager = ContextManager()
