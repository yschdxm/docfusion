"""
工具执行器 - 解析和执行LLM的工具调用

负责:
- 解析LLM的工具调用请求
- 验证参数
- 执行对应工具
- 错误处理和重试
- 流式事件推送
"""

import json
from typing import Dict, Any, Optional, List
import logging

from app.agent.base.tool import ToolContext, ToolResult
from app.agent.core.registry import ToolRegistry


logger = logging.getLogger(__name__)


class ToolExecutor:
    """工具执行器

    执行LLM发起的工具调用，管理执行流程。
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        logger.info(f"ToolExecutor初始化完成 | 注册工具数: {len(registry.get_all_tools())}")

    async def execute(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
        context: ToolContext,
        max_retries: int = 3
    ) -> ToolResult:
        """执行工具调用

        Args:
            tool_name: 工具名称
            tool_params: 工具参数
            context: 执行上下文
            max_retries: 最大重试次数

        Returns:
            ToolResult: 执行结果
        """
        logger.info(f"[ToolExecutor] 开始执行工具 | {tool_name}")
        logger.info(f"[ToolExecutor] 参数: {json.dumps(tool_params, ensure_ascii=False, default=str)[:500]}")
        logger.info(f"[ToolExecutor] 上下文 | Session: {context.session_id}, 文件数: {len(context.file_ids)}")

        # 获取工具
        tool = self.registry.get(tool_name)
        if tool is None:
            error_msg = f"工具不存在: {tool_name}"
            logger.error(f"[ToolExecutor] {error_msg}")
            logger.error(f"[ToolExecutor] 可用工具: {[t.name for t in self.registry.get_all_tools()]}")
            return ToolResult(
                success=False,
                error=error_msg
            )

        logger.info(f"[ToolExecutor] 找到工具 | {tool_name}: {tool.description[:100]}...")

        # 检查工具是否被允许
        if not self.registry.is_tool_allowed(tool_name):
            error_msg = f"工具被禁用: {tool_name}"
            logger.error(f"[ToolExecutor] {error_msg}")
            return ToolResult(
                success=False,
                error=error_msg
            )

        # 执行工具（带重试）
        last_error = None
        for attempt in range(max_retries):
            try:
                logger.info(f"[ToolExecutor] {tool_name} | 执行尝试 {attempt + 1}/{max_retries}")
                result = await tool.run(tool_params, context)

                if result.success:
                    logger.info(f"[ToolExecutor] {tool_name} | 执行成功 | 耗时: {result.execution_time_ms}ms")
                    if result.data:
                        data_preview = json.dumps(result.data, ensure_ascii=False, default=str)[:300]
                        logger.debug(f"[ToolExecutor] {tool_name} | 结果预览: {data_preview}...")
                    if result.metadata:
                        logger.debug(f"[ToolExecutor] {tool_name} | 元数据: {result.metadata}")
                    return result

                # 记录错误，准备重试
                last_error = result.error
                logger.warning(f"[ToolExecutor] {tool_name} | 执行失败 (尝试 {attempt + 1}/{max_retries}): {result.error}")

                if attempt < max_retries - 1:
                    import asyncio
                    wait_time = 0.5 * (attempt + 1)  # 递增等待时间
                    logger.info(f"[ToolExecutor] {tool_name} | 等待 {wait_time}s 后重试...")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                last_error = str(e)
                logger.exception(f"[ToolExecutor] {tool_name} | 执行异常 (尝试 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    import asyncio
                    wait_time = 0.5 * (attempt + 1)
                    logger.info(f"[ToolExecutor] {tool_name} | 等待 {wait_time}s 后重试...")
                    await asyncio.sleep(wait_time)

        # 所有重试都失败
        final_error = f"工具执行失败，已重试{max_retries}次。最后错误: {last_error}"
        logger.error(f"[ToolExecutor] {tool_name} | {final_error}")
        return ToolResult(
            success=False,
            error=final_error
        )

    def parse_tool_call(self, tool_call_data: Any) -> Optional[tuple[str, Dict[str, Any]]]:
        """解析LLM的工具调用数据

        支持多种格式:
        1. OpenAI格式: {"name": "tool_name", "arguments": {...}}
        2. JSON字符串: '{"name": "tool_name", "arguments": {...}}'
        3. 直接格式: {"tool": "tool_name", "params": {...}}

        Args:
            tool_call_data: 工具调用数据

        Returns:
            (tool_name, params) 或 None
        """
        logger.debug(f"[ToolExecutor] 解析工具调用 | 类型: {type(tool_call_data).__name__}")

        try:
            # 如果是字符串，先解析JSON
            if isinstance(tool_call_data, str):
                tool_call_data = json.loads(tool_call_data)
                logger.debug("[ToolExecutor] 工具调用是JSON字符串，已解析")

            if not isinstance(tool_call_data, dict):
                logger.warning(f"[ToolExecutor] 工具调用数据格式错误: 期望dict，得到{type(tool_call_data).__name__}")
                return None

            # OpenAI格式
            if "name" in tool_call_data and "arguments" in tool_call_data:
                name = tool_call_data["name"]
                args = tool_call_data["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)
                logger.debug(f"[ToolExecutor] 解析OpenAI格式工具调用 | {name}")
                return name, args

            # 直接格式
            if "tool" in tool_call_data and "params" in tool_call_data:
                name = tool_call_data["tool"]
                params = tool_call_data["params"]
                logger.debug(f"[ToolExecutor] 解析直接格式工具调用 | {name}")
                return name, params

            # 其他可能的格式
            if "function" in tool_call_data:
                func = tool_call_data["function"]
                if isinstance(func, dict):
                    name = func.get("name")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    logger.debug(f"[ToolExecutor] 解析function格式工具调用 | {name}")
                    return name, args

            logger.warning(f"[ToolExecutor] 无法识别的工具调用格式: {list(tool_call_data.keys())}")
            return None

        except json.JSONDecodeError as e:
            logger.error(f"[ToolExecutor] 工具调用JSON解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[ToolExecutor] 解析工具调用失败: {e}")
            return None

    def format_tool_result(self, tool_name: str, result: ToolResult) -> str:
        """格式化工具结果为文本，供LLM使用

        对于返回大量记录的工具（如 query_pg_database），做智能压缩：
        只展示摘要 + 前5条 + 后2条，避免撑爆 LLM 上下文。

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            格式化后的文本
        """
        if result.success:
            if result.data and tool_name == "query_pg_database":
                data_str = self._compress_query_result(result.data)
            else:
                data_str = json.dumps(result.data, ensure_ascii=False, indent=2) if result.data else "成功"
            formatted = f"""工具 "{tool_name}" 执行成功

执行时间: {result.execution_time_ms}ms

结果:
{data_str}
"""
            logger.debug(f"[ToolExecutor] 格式化工具结果 | {tool_name} | 长度: {len(formatted)} 字符")
            return formatted
        else:
            formatted = f"""工具 "{tool_name}" 执行失败

错误: {result.error}

请尝试其他方法或修正参数后重试。
"""
            logger.debug(f"[ToolExecutor] 格式化工具错误结果 | {tool_name} | 错误: {result.error}")
            return formatted

    def _compress_query_result(self, data: Any) -> str:
        """压缩 query_pg_database 等返回大量记录的结果。

        只给 LLM 展示摘要 + 前5条 + 后2条，避免上下文爆炸。
        完整数据仍保留在 ToolResult.data 中供工具内部使用。
        """
        if not isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False, indent=2)

        records = data.get("records", [])
        if len(records) <= 10:
            return json.dumps(data, ensure_ascii=False, indent=2)

        # 构建摘要
        columns = data.get("columns", [])
        records_count = data.get("records_count", len(records))
        total_count = data.get("total_count", records_count)
        query = data.get("query", "")

        summary_parts = [f"共 {records_count} 条记录"]
        if total_count > records_count:
            summary_parts.append(f"（去重前 {total_count} 条）")
        if columns:
            summary_parts.append(f"列: {columns}")
        summary = "，".join(summary_parts)

        # 前5条 + 后2条预览
        preview_head = json.dumps(records[:5], ensure_ascii=False, indent=2)
        preview_tail = json.dumps(records[-2:], ensure_ascii=False, indent=2)
        omitted = len(records) - 7

        return f"""查询: {query}
{summary}

前5条:
{preview_head}

... (省略 {omitted} 条) ...

后2条:
{preview_tail}

提示: 如需填写表格，请使用 fill_table(source_query=...) 自动查询并填充，无需手动搬运数据。"""

    def get_available_tools_description(self) -> str:
        """生成可用工具的说明文本，用于System Prompt"""
        tools = self.registry.get_all_tools()
        descriptions = []

        for tool in tools:
            desc = f"- {tool.name}: {tool.description}"
            descriptions.append(desc)

        result = "\n".join(descriptions)
        logger.debug(f"[ToolExecutor] 生成工具描述 | 共 {len(tools)} 个工具")
        return result

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """获取OpenAI/MiMO格式的工具定义

        Returns:
            OpenAI Function Calling格式的工具列表
        """
        schemas = self.registry.get_function_schemas()
        logger.debug(f"[ToolExecutor] 获取OpenAI工具定义 | 共 {len(schemas)} 个工具")
        return schemas

    def get_openai_tools_description(self) -> str:
        """生成OpenAI格式的工具描述"""
        tools = self.get_openai_tools()
        if not tools:
            return "无可用工具"

        descriptions = []
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            descriptions.append(f"- {name}: {desc}")

        return "\n".join(descriptions)
