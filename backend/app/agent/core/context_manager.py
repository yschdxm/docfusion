"""上下文管理器 - 对话历史压缩与 token 预算管理

参考 Hermes-Agent 的 trajectory_compressor 和 Claude Code 的 per-tool truncation，
提供：
- 滑动窗口 + 摘要压缩：旧对话摘要化，保留最近 N 轮
- Tool Result 智能截断：按工具类型截断过长的结果
- token 预算管理：估算 token 数，超过阈值自动触发压缩
"""

import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# 各工具的结果截断限制（字符数）
TOOL_RESULT_LIMITS = {
    "query_pg_database": 4000,
    "query_knowledge_graph": 3000,
    "rag_search": 3000,
    "extract_from_documents": 4000,
    "read_document": 5000,
    "get_table_structure": 3000,
    "fill_table": 2000,
    "list_documents": 2000,
    # 文档编辑工具
    "replace_text": 1000,
    "rewrite_paragraph": 1000,
    "insert_after": 1000,
    "heading_promote": 500,
    "list_format": 500,
    "paragraph_split": 500,
    "set_text_style": 500,
    "convert": 1000,
}

# 默认截断限制
DEFAULT_TOOL_RESULT_LIMIT = 2000

# 保留最近 N 轮对话（每轮 = 1 user + 1 assistant）
MAX_HISTORY_ROUNDS = 10

# token 阈值（约 4 字符 = 1 token）
MAX_CONTEXT_TOKENS = 80000
COMPRESS_THRESHOLD_TOKENS = 60000


class ContextManager:
    """上下文管理器"""

    @staticmethod
    def estimate_tokens(messages: List[Dict[str, str]]) -> int:
        """粗略估算消息列表的 token 数。

        策略：中文约 2 字符/token，英文约 4 字符/token。
        简化为：总字符数 / 3（中英混合的平均值）。
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total_chars += len(part["text"])
            # tool_calls 的 arguments 也计入
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        func = tc.get("function", {})
                        total_chars += len(func.get("name", ""))
                        total_chars += len(str(func.get("arguments", "")))
        return total_chars // 3

    @staticmethod
    def truncate_tool_result(tool_name: str, result_text: str) -> str:
        """按工具类型智能截断结果。

        保留开头和结尾，中间用省略提示替代。
        """
        limit = TOOL_RESULT_LIMITS.get(tool_name, DEFAULT_TOOL_RESULT_LIMIT)

        if len(result_text) <= limit:
            return result_text

        # 保留前 70% 和后 20%，中间截断
        head_size = int(limit * 0.7)
        tail_size = int(limit * 0.2)

        head = result_text[:head_size]
        tail = result_text[-tail_size:]
        omitted = len(result_text) - head_size - tail_size

        return f"{head}\n\n... [省略 {omitted} 字符] ...\n\n{tail}"

    @staticmethod
    def truncate_messages(messages: List[Dict[str, str]], max_rounds: int = MAX_HISTORY_ROUNDS) -> List[Dict[str, str]]:
        """滑动窗口截断：保留 system prompt + 最近 N 轮对话。

        不依赖 LLM 的轻量级压缩方式。
        """
        if not messages:
            return messages

        # 保留 system message（第一条）
        system_msgs = []
        other_msgs = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msgs.append(msg)
            else:
                other_msgs.append(msg)

        # 计算需要保留的消息数（每轮 = user + assistant，可能还有 tool）
        # 粗略保留最近 max_rounds * 3 条消息（user + assistant + tool）
        max_msgs = max_rounds * 3
        if len(other_msgs) <= max_msgs:
            return messages

        # 截断旧消息
        truncated_other = other_msgs[-max_msgs:]
        omitted_count = len(other_msgs) - max_msgs

        # 在截断位置插入摘要提示
        summary_msg = {
            "role": "system",
            "content": f"[上下文压缩] 已省略前 {omitted_count} 条历史消息。以下为最近的对话。"
        }

        result = system_msgs + [summary_msg] + truncated_other
        logger.info(f"[ContextManager] 消息截断: {len(messages)} -> {len(result)} 条 (省略 {omitted_count} 条)")
        return result

    @staticmethod
    def compress_tool_results_in_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """压缩消息列表中过长的 tool 消息内容。

        扫描所有 role='tool' 的消息，对过长内容进行截断。
        """
        compressed_count = 0

        for msg in messages:
            if msg.get("role") != "tool":
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # 检查是否过长（超过默认限制的 2 倍）
            if len(content) <= DEFAULT_TOOL_RESULT_LIMIT * 2:
                continue

            # 尝试从内容中推断工具名
            tool_name = ContextManager._infer_tool_name(msg, messages)

            # 截断
            original_len = len(content)
            msg["content"] = ContextManager.truncate_tool_result(tool_name, content)
            compressed_count += 1
            logger.debug(f"[ContextManager] 压缩 tool 结果: {tool_name} | {original_len} -> {len(msg['content'])} 字符")

        if compressed_count > 0:
            logger.info(f"[ContextManager] 共压缩 {compressed_count} 条 tool 消息")

        return messages

    @staticmethod
    def _infer_tool_name(tool_msg: Dict, all_messages: List[Dict]) -> str:
        """从上下文推断 tool 消息对应的工具名。

        查找 tool_msg 之前的 assistant 消息中的 tool_calls。
        """
        tool_call_id = tool_msg.get("tool_call_id", "")
        if not tool_call_id:
            return "unknown"

        # 在所有消息中查找对应的 tool_call
        for msg in all_messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                        return tc.get("function", {}).get("name", "unknown")

        return "unknown"

    @classmethod
    def should_compress(cls, messages: List[Dict[str, str]]) -> bool:
        """判断是否需要压缩上下文。"""
        estimated_tokens = cls.estimate_tokens(messages)
        return estimated_tokens > COMPRESS_THRESHOLD_TOKENS

    @classmethod
    def auto_compress(cls, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """自动压缩上下文。

        策略：
        1. 先压缩过长的 tool 结果（无损）
        2. 如果仍然超限，使用滑动窗口截断旧消息
        """
        # 第一步：压缩 tool 结果
        messages = cls.compress_tool_results_in_messages(messages)

        # 第二步：检查是否仍需截断
        if cls.should_compress(messages):
            messages = cls.truncate_messages(messages)
            logger.info(f"[ContextManager] 自动压缩完成 | 估算 tokens: {cls.estimate_tokens(messages)}")
        else:
            logger.debug(f"[ContextManager] 无需进一步压缩 | 估算 tokens: {cls.estimate_tokens(messages)}")

        return messages
