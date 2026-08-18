"""
Agent运行时 - 核心协调器

参考OpenClaw的Agent Loop设计，负责：
- 管理Agent生命周期
- 协调LLM调用和工具执行
- 维护对话上下文
- 生成流式事件
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from uuid import uuid4
import asyncio

from app.agent.core.registry import ToolRegistry
from app.agent.core.executor import ToolExecutor
from app.agent.core.event_log import TaskEventLog
from app.agent.core.tracker import StepTracker, StepType
from app.agent.base.tool import ToolContext

from app.services.llm_service import llm_service
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select


logger = logging.getLogger(__name__)

# 单条工具结果消息的最大字符数（超出截断，防止撑爆上下文）
MAX_TOOL_RESULT_CHARS = 20000


DEFAULT_SYSTEM_PROMPT = """你是一个智能文档处理助手。分析用户需求，使用可用工具完成任务，并向用户清晰报告结果。"""


class AgentRuntime:
    """Agent运行时

    协调LLM调用和工具执行，支持流式输出。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        max_iterations: int = 30,
        max_tool_retries: int = 3,
        system_prompt: Optional[str] = None
    ):
        self.registry = registry
        self.executor = ToolExecutor(registry)
        self.max_iterations = max_iterations
        self.max_tool_retries = max_tool_retries
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        logger.info(f"[AgentRuntime] 初始化 | max_iterations={max_iterations}, max_tool_retries={max_tool_retries}")

    async def run(
        self,
        message: str,
        file_ids: List[str],
        template_id: Optional[str] = None,
        conversation_history: List[Dict[str, str]] = None,
        event_log: Optional[TaskEventLog] = None,
        step_tracker: Optional[StepTracker] = None,
        user_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        user_selected_model: Optional[str] = None,
        db=None,
        conversation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        auto_review: bool = True,
    ) -> Dict[str, Any]:
        """运行Agent

        只管向 event_log 发布事件，不感知 HTTP 连接死活。
        取消唯一来源：cancel_event（由 TaskManager.cancel 设置）。
        终态事件由本方法在相应分支发布；TaskSupervisor 兜底保证恰好一次并 finish。
        """
        context = ToolContext(
            session_id=f"session_{datetime.utcnow().timestamp()}",
            user_id=user_id,
            file_ids=file_ids,
            template_id=template_id,
            conversation_history=conversation_history or [],
            metadata={
                "cancel_event": cancel_event,  # 委派子Agent时传播取消信号
                # run_id 标识同一轮指令（委派子Agent时透传），用于文档版本化的同run判定
                "run_id": run_id or uuid4().hex,
                "conversation_id": conversation_id,
                # 人工确认开关：False 时 dry_run 结果需用户确认后才 commit
                "auto_review": auto_review,
            },
        )

        logger.info("=" * 60)
        logger.info("[AgentRuntime.run] 任务开始")
        logger.info(f"[AgentRuntime.run] Session: {context.session_id}")
        logger.info(f"[AgentRuntime.run] 用户输入: {message[:100]}..." if len(message) > 100 else f"[AgentRuntime.run] 用户输入: {message}")
        logger.info(f"[AgentRuntime.run] file_ids={file_ids}, template_id={template_id}")
        logger.info("=" * 60)

        tracker = step_tracker or StepTracker()
        stream = event_log or TaskEventLog()

        try:
            result = await self._execute_loop(
                message=message,
                context=context,
                tracker=tracker,
                stream=stream,
                cancel_event=cancel_event,
                user_selected_model=user_selected_model,
                db=db,
            )
            logger.info(f"[AgentRuntime.run] 任务完成 | success={result.get('success')}")
            return result
        except asyncio.CancelledError:
            logger.info("[AgentRuntime.run] 任务被取消")
            raise
        except Exception as e:
            logger.exception(f"[AgentRuntime.run] 任务异常: {e}")
            await stream.emit_failed(str(e))
            return {"success": False, "error": str(e), "steps": tracker.to_dict()}

    async def _execute_loop(
        self,
        message: str,
        context: ToolContext,
        tracker: StepTracker,
        stream: TaskEventLog,
        cancel_event: Optional[asyncio.Event] = None,
        user_selected_model: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        """执行主循环 - 使用原生工具调用和流式输出"""
        logger.info("[AgentRuntime._execute_loop] 进入执行循环 (原生工具调用)")

        # 记录任务开始时间和token统计
        task_start_time = datetime.utcnow()
        accumulated_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "llm_calls": 0,
        }
        # 存为实例属性，供父agent读取子agent的usage
        self.accumulated_usage = accumulated_usage

        # 检查取消信号
        def check_cancelled():
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("任务被取消")

        # 获取OpenAI格式的工具定义
        logger.info("[AgentRuntime._execute_loop] 获取工具定义...")
        try:
            openai_tools = self.executor.get_openai_tools()
            logger.info(f"[AgentRuntime._execute_loop] 获取到 {len(openai_tools)} 个工具定义")
        except Exception as e:
            logger.exception(f"[AgentRuntime._execute_loop] 获取工具定义失败: {e}")
            raise

        # 构建对话历史
        logger.info("[AgentRuntime._execute_loop] 构建对话消息...")

        # 构建用户上下文信息（选择的文件）
        user_context = await self._build_user_context(context)
        system_content = self.system_prompt + user_context

        # 人工确认模式：约束 LLM 在 dry_run 后停下等用户确认，不要自行 commit
        if context.metadata.get("auto_review") is False:
            system_content += (
                "\n\n## 人工确认模式（用户已开启）\n"
                "fill_table_execute / fill_form 的 mode=dry_run 返回后，禁止立即调用 mode=commit。"
                "你应总结校验报告（总项数、异常项及处理建议），然后结束本轮回复，等待用户确认。\n"
                "用户点确认后由服务端直接按暂存参数执行写入，不会再调用你，无需等待也无需重复操作。\n"
                "即使你认为用户已确认（例如历史消息中有确认记录），也禁止自行 commit——"
                "commit 只能由服务端在用户点击确认后触发，你的任何 commit 调用都会被拒绝。\n"
                "若用户用文字表达修改意愿（而非确认），按新意愿调整映射并重新 dry_run。"
            )

        messages = [{"role": "system", "content": system_content}]
        messages.extend(context.conversation_history)
        messages.append({"role": "user", "content": message})

        logger.info(f"[AgentRuntime._execute_loop] 构建完成 | 消息数: {len(messages)}")

        final_result = None
        total_tool_calls = 0
        # 最近一次成功的文档产出（下载信息），用于 completed 事件携带 output_file_id/download_url，
        # 使自动审核模式（无确认卡片）也能渲染下载卡片并被持久化（_extract_action_data 读 result.download_url）
        last_download: dict = {}

        def build_task_stats():
            """构建任务统计信息"""
            duration = (datetime.utcnow() - task_start_time).total_seconds() * 1000
            return {
                "task_stats": {
                    "duration_ms": round(duration),
                    "total_tokens": accumulated_usage["total_tokens"],
                    "prompt_tokens": accumulated_usage["prompt_tokens"],
                    "completion_tokens": accumulated_usage["completion_tokens"],
                    "cached_tokens": accumulated_usage["cached_tokens"],
                    "reasoning_tokens": accumulated_usage["reasoning_tokens"],
                    "llm_calls": accumulated_usage["llm_calls"],
                    "iterations": iteration + 1,
                }
            }

        for iteration in range(self.max_iterations):
            # 检查是否被取消（唯一取消来源：cancel_event）
            if cancel_event and cancel_event.is_set():
                logger.info("[AgentRuntime._execute_loop] 检测到取消信号，终止执行")
                raise asyncio.CancelledError("任务被取消")

            logger.info(f"[AgentRuntime._execute_loop] ===== 迭代 {iteration + 1}/{self.max_iterations} =====")

            # 发送进度信息（每5次迭代）
            if iteration > 0 and iteration % 5 == 0:
                await stream.emit_system_message(f"任务进行中，已完成 {iteration} 步...", level="info")

            # 创建思考步骤
            step = tracker.create_step(
                step_type=StepType.THINKING,
                name="思考中",
                description="LLM思考并决定下一步行动"
            )
            tracker.start_step(step.id)
            await stream.emit_thinking_start(step.id, "正在思考...")

            # 调用LLM (流式)
            logger.info(f"[AgentRuntime._execute_loop] 准备调用LLM | 当前消息数: {len(messages)}")
            try:
                response_start = datetime.utcnow()

                # 流式调用LLM
                full_content = ""
                full_reasoning = ""
                tool_calls_buffer = []
                finish_reason = None  # 初始化 finish_reason，用于流结束后检查

                llm_stream = await llm_service.chat_completion(
                    messages=messages,
                    temperature=0.7,
                    # max_tokens 使用模型默认值
                    enable_thinking=True,
                    stream=True,
                    tools=openai_tools,
                    user_selected_model=user_selected_model,
                    db=db,
                )

                has_emitted_thinking_end = False
                has_emitted_content = False

                async for chunk in llm_stream:
                    # 检测是否被取消（取消时尽快中止 LLM 消费）
                    if cancel_event and cancel_event.is_set():
                        logger.info("[AgentRuntime._execute_loop] 检测到取消信号，中止LLM消费")
                        raise asyncio.CancelledError("任务被取消")

                    # 检测usage统计chunk
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                        accumulated_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                        accumulated_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                        accumulated_usage["total_tokens"] += usage.get("total_tokens", 0)
                        accumulated_usage["cached_tokens"] += usage.get("cached_tokens", 0)
                        accumulated_usage["reasoning_tokens"] += usage.get("reasoning_tokens", 0)
                        continue

                    # 处理思考内容
                    if chunk.get("reasoning_content"):
                        # 如果之前已经开始输出内容，现在又出现思考，说明是交替模式
                        # 需要重新开启思考状态（如果已结束）
                        if has_emitted_thinking_end and has_emitted_content:
                            has_emitted_thinking_end = False
                            await stream.emit_thinking_start(step.id, "继续思考...")
                        full_reasoning += chunk["reasoning_content"]
                        await stream.emit_thinking_chunk(chunk["reasoning_content"])

                    # 处理正式内容 - 实时推送
                    if chunk.get("content"):
                        # 如果有思考内容且还没发送thinking_end，先发送thinking_end
                        if full_reasoning and not has_emitted_thinking_end:
                            has_emitted_thinking_end = True
                            step.name = "思考完成"
                            await stream.emit_thinking_end("思考完成")
                        has_emitted_content = True
                        full_content += chunk["content"]
                        await stream.emit_content_chunk(chunk["content"])

                    # 处理工具调用 (流式中分段到达)
                    if chunk.get("tool_calls"):
                        for tc in chunk["tool_calls"]:
                            index = tc.get("index", 0)
                            if index >= len(tool_calls_buffer):
                                tool_calls_buffer.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})

                            if tc.get("id"):
                                tool_calls_buffer[index]["id"] = tc["id"]
                            if tc.get("function", {}).get("name"):
                                tool_calls_buffer[index]["function"]["name"] = tc["function"]["name"]
                            if tc.get("function", {}).get("arguments"):
                                tool_calls_buffer[index]["function"]["arguments"] += tc["function"]["arguments"]

                    # 检查是否完成
                    finish_reason = chunk.get("finish_reason")
                    if finish_reason:
                        content_len = len(chunk.get('content') or '')
                        reasoning_len = len(chunk.get('reasoning_content') or '')
                        tool_calls = chunk.get('tool_calls') or []
                        tool_calls_count = len(tool_calls)
                        logger.info(f"[AgentRuntime._execute_loop] LLM返回finish_reason={finish_reason}, content长度={content_len}, reasoning长度={reasoning_len}, tool_calls数量={tool_calls_count}")
                        # 注意：这里不立即 break，让循环自然结束
                        # 因为当前 chunk 可能还包含内容或工具调用
                        # 如果是 stop 且没有内容/工具调用，会在后续逻辑中处理

                response_time = (datetime.utcnow() - response_start).total_seconds()
                accumulated_usage["llm_calls"] += 1
                logger.info(f"[AgentRuntime._execute_loop] LLM流式调用完成 | 耗时: {response_time:.2f}s | 内容长度: {len(full_content)} | 思考长度: {len(full_reasoning)} | 工具调用: {len(tool_calls_buffer)}")

                # 发送实时统计更新
                await stream.emit_stats_update(build_task_stats()["task_stats"])

            except Exception as e:
                logger.exception(f"[AgentRuntime._execute_loop] LLM调用失败: {e}")
                tracker.fail_step(step.id, str(e))
                # 判断错误类型，发送友好的错误信息
                error_str = str(e).lower()
                if "connection" in error_str or "readerror" in error_str or "连接" in error_str:
                    user_msg = "连接意外中断，请重试"
                elif "timeout" in error_str or "超时" in error_str:
                    user_msg = "请求超时，请重试"
                elif "rate_limit" in error_str or "频率" in error_str:
                    user_msg = "请求频率过高，请稍后重试"
                else:
                    user_msg = "任务执行失败，请重试"
                await stream.emit_failed(user_msg, {"error": str(e)})
                return {"success": False, "error": user_msg, "steps": tracker.to_dict()}

            # 检测是否被取消（LLM循环后）
            if cancel_event and cancel_event.is_set():
                logger.info("[AgentRuntime._execute_loop] 检测到取消信号，中止执行循环")
                raise asyncio.CancelledError("任务被取消")

            # 更新思考内容
            tracker.update_thinking(step.id, full_reasoning)
            # 如果还没有发送thinking_end（没有content的情况），在这里发送
            if not has_emitted_thinking_end:
                step.name = "思考完成"
                await stream.emit_thinking_end("思考完成")

            # 如果没有工具调用，检查是否有实际回复内容
            if not tool_calls_buffer:
                # 检查内容是否为空或只有空白字符
                content_stripped = full_content.strip() if full_content else ""
                if not content_stripped:
                    # 没有工具调用且没有回复内容
                    # 检查上一条消息是否是工具执行结果
                    last_msg = messages[-1] if messages else None
                    is_after_tool_result = last_msg and last_msg.get('role') == 'tool'

                    # 检查 finish_reason，如果是异常情况不应该认为任务已完成
                    # 'stop' 和 'tool_calls' 是正常情况，其他都是异常
                    is_abnormal_finish = finish_reason and finish_reason not in ['stop', 'tool_calls']

                    if is_abnormal_finish:
                        # 异常 finish_reason，记录错误
                        error_msg = f"LLM返回异常状态（finish_reason={finish_reason}），无法继续处理"
                        logger.error(f"[AgentRuntime._execute_loop] {error_msg}")
                        tracker.fail_step(step.id, error_msg)
                        await stream.emit_error(error_msg)
                        await stream.emit_failed(error_msg, {"reasoning": full_reasoning, "finish_reason": finish_reason})
                        return {"success": False, "error": error_msg, "steps": tracker.to_dict()}

                    # 如果有思考内容，说明LLM完成了思考但没有生成最终回复（可能是任务已完成）
                    # 如果没有思考内容但刚执行完工具，也可能是任务已完成
                    # 如果都没有，才视为错误
                    if full_reasoning and full_reasoning.strip():
                        # 有思考内容但没有最终回复，说明LLM完成了任务但不需要回复
                        logger.info(f"[AgentRuntime._execute_loop] LLM完成任务但无最终回复（有思考内容），思考长度: {len(full_reasoning)}")
                        tracker.complete_step(step.id, {"response": "", "reasoning": full_reasoning, "note": "LLM完成任务但无最终回复"})
                        await stream.emit_completed("", {**build_task_stats(), "final_response": "", "reasoning": full_reasoning, "note": "任务已完成", **last_download})
                        return {"success": True, "message": "", "reasoning": full_reasoning, "steps": tracker.to_dict()}
                    elif is_after_tool_result:
                        # 刚执行完工具，LLM没有回复内容，可能是任务已完成（如填表任务）
                        # 但只有在 finish_reason 正常（stop 或 tool_calls）时才认为是完成
                        logger.info("[AgentRuntime._execute_loop] LLM在工具执行后无回复，可能是任务已完成")
                        tracker.complete_step(step.id, {"response": "", "reasoning": full_reasoning, "note": "任务已完成（工具执行后无回复）"})
                        await stream.emit_completed("", {**build_task_stats(), "final_response": "", "reasoning": full_reasoning, "note": "任务已完成", **last_download})
                        return {"success": True, "message": "", "reasoning": full_reasoning, "steps": tracker.to_dict()}
                    else:
                        # 没有工具调用且没有内容/思考，说明LLM返回为空（可能是content_filter或其他问题）
                        error_msg = f"LLM未返回有效内容（finish_reason={finish_reason}），思考内容长度: {len(full_reasoning)}, 对话消息数: {len(messages)}"
                        logger.error(f"[AgentRuntime._execute_loop] {error_msg}")

                        # 获取最近的工具调用信息
                        tool_calls_info = []
                        for msg in messages:
                            if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                                for tc in msg['tool_calls']:
                                    tool_calls_info.append(tc.get('function', {}).get('name', 'N/A'))

                        logger.error(f"[AgentRuntime._execute_loop] 最近工具调用: {tool_calls_info}")
                        logger.error(f"[AgentRuntime._execute_loop] 最后一条用户消息: {messages[-1].get('content', '')[:200]}")

                        tracker.fail_step(step.id, error_msg)
                        await stream.emit_error(error_msg)
                        await stream.emit_failed(error_msg, {"reasoning": full_reasoning, "message_count": len(messages)})
                        return {"success": False, "error": error_msg, "steps": tracker.to_dict()}

                # 有实际回复内容，正常完成任务
                tracker.complete_step(step.id, {"response": full_content, "reasoning": full_reasoning})
                await stream.emit_completed(full_content, {**build_task_stats(), "final_response": full_content, "reasoning": full_reasoning, **last_download})
                logger.info(f"[AgentRuntime._execute_loop] 任务完成 | 总迭代: {iteration + 1} | 总工具调用: {total_tool_calls}")
                return {"success": True, "message": full_content, "reasoning": full_reasoning, "steps": tracker.to_dict()}

            tracker.complete_step(step.id)
            await stream.emit_thinking_end(f"决定调用 {len(tool_calls_buffer)} 个工具")

            # 如果有回复内容且有工具调用，先发送中间回复事件（在工具调用前）
            if full_content.strip():
                await stream.emit_content_end()
                await stream.emit_assistant_message(full_content.strip())
                logger.info(f"[AgentRuntime._execute_loop] 发送中间回复（长度: {len(full_content)}）")

            # 执行工具调用
            tool_messages = []
            for tool_call in tool_calls_buffer:
                tool_name = tool_call["function"]["name"]
                try:
                    tool_args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError as e:
                    logger.error(f"[AgentRuntime._execute_loop] 工具 {tool_name} 参数JSON解析失败: {e}")
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"参数JSON解析失败: {str(e)}。请检查参数格式后重试。"
                    })
                    continue
                total_tool_calls += 1

                logger.info(f"[AgentRuntime._execute_loop] 执行工具: {tool_name}")

                # 创建工具调用步骤
                tool_step = tracker.create_step(
                    step_type=StepType.TOOL_CALL,
                    name=f"调用 {tool_name}",
                    description=f"调用工具: {tool_name}",
                    tool_name=tool_name,
                    tool_params=tool_args
                )
                tracker.start_step(tool_step.id)
                await stream.emit_step_start(tool_step.id, tool_step.name, tool_step.description)
                await stream.emit_tool_call(tool_name, tool_args)

                # 执行工具前检查是否已取消
                if cancel_event and cancel_event.is_set():
                    logger.info("[AgentRuntime._execute_loop] 检测到取消信号，中止工具执行")
                    raise asyncio.CancelledError("任务被取消")

                # 执行工具
                logger.info(f"[AgentRuntime._execute_loop] 调用executor.execute: {tool_name}")
                tool_start = datetime.utcnow()
                result = await self.executor.execute(
                    tool_name=tool_name,
                    tool_params=tool_args,
                    context=context,
                    max_retries=self.max_tool_retries
                )
                tool_time = (datetime.utcnow() - tool_start).total_seconds()

                # 记录结果
                if result.success:
                    logger.info(f"[AgentRuntime._execute_loop] 工具 {tool_name} 成功 | 耗时: {tool_time:.2f}s")
                    if isinstance(result.data, dict) and result.data.get("download_url"):
                        last_download = {
                            "output_file_id": result.data.get("output_file_id"),
                            "output_filename": result.data.get("output_filename"),
                            "download_url": result.data.get("download_url"),
                        }
                    tracker.complete_step(
                        tool_step.id,
                        result=result.data if isinstance(result.data, dict) else {"data": result.data}
                    )
                    await stream.emit_tool_result(
                        tool_name=tool_name,
                        result=result.data if isinstance(result.data, dict) else {"data": str(result.data)},
                        execution_time_ms=result.execution_time_ms
                    )
                    # 人工确认模式：工具结果标记了 requires_confirmation 时发确认事件
                    # （前端据此渲染确认卡片；确认/取消经 action_response 通道，不产生用户消息）
                    if result.metadata.get("requires_confirmation"):
                        action_data = {
                            "action_id": result.metadata.get("action_id"),
                            # preview 在 metadata 中（LLM 不可见）；report 在 data 中
                            "preview": result.metadata.get("preview"),
                            "dry_run_report": result.data.get("dry_run_report") if isinstance(result.data, dict) else None,
                        }
                        await stream.emit_action_required(
                            action_type="fill_confirm",
                            action_data=action_data,
                            message=result.data.get("summary", "") if isinstance(result.data, dict) else "",
                        )
                    await stream.emit_step_end(tool_step.id, "工具执行成功")
                else:
                    logger.error(f"[AgentRuntime._execute_loop] 工具 {tool_name} 失败 | 耗时: {tool_time:.2f}s | 错误: {result.error}")
                    tracker.fail_step(tool_step.id, result.error)
                    await stream.emit_tool_error(tool_name, result.error)
                    await stream.emit_step_end(tool_step.id, f"工具执行失败: {result.error}")

                # 收集工具结果消息（超大结果截断，避免撑爆上下文）
                result_content = json.dumps(result.data, ensure_ascii=False, default=str) if result.success else str(result.error)
                if len(result_content) > MAX_TOOL_RESULT_CHARS:
                    result_content = (
                        result_content[:MAX_TOOL_RESULT_CHARS]
                        + f"...[结果过长已截断，原始长度 {len(result_content)} 字符。"
                        "如需完整内容请用更精确的参数分次获取]"
                    )
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result_content
                })

                final_result = result

            # 按 OpenAI 规范组装：一条 assistant 消息携带全部 tool_calls，
            # 随后按顺序跟 N 条 tool 结果消息
            messages.append({
                "role": "assistant",
                "content": full_content if full_content else None,
                "reasoning_content": full_reasoning,
                "tool_calls": tool_calls_buffer
            })
            messages.extend(tool_messages)
            logger.debug(f"[AgentRuntime._execute_loop] 已添加工具结果到对话历史 | 当前消息数: {len(messages)}")

            logger.info(f"[AgentRuntime._execute_loop] 迭代 {iteration + 1} 完成 | 调用 {len(tool_calls_buffer)} 个工具")

        # 达到最大迭代次数
        logger.warning(f"[AgentRuntime._execute_loop] 达到最大迭代次数: {self.max_iterations}")
        await stream.emit_warning(f"达到最大迭代次数限制 ({self.max_iterations})")
        await stream.emit_completed(
            "任务已部分完成，但达到了最大迭代次数限制。",
            {**build_task_stats(), "partial_result": final_result.data if final_result else None}
        )

        return {
            "success": True,
            "message": "任务已部分完成，但达到了最大迭代次数限制。",
            "steps": tracker.to_dict(),
            "reached_max_iterations": True
        }

    async def _build_user_context(self, context: ToolContext) -> str:
        """构建用户上下文信息（选择的文件）

        将用户选择的文档信息添加到System Prompt中，让LLM知道有哪些文件可用。
        """
        context_parts = []

        # 查询文档详情
        all_file_ids = list(context.file_ids)
        if context.template_id:
            all_file_ids.append(context.template_id)

        doc_details = {}
        if all_file_ids:
            try:
                async with async_session() as db:
                    # 将字符串ID转换为UUID
                    from uuid import UUID
                    uuid_ids = []
                    for fid in all_file_ids:
                        try:
                            uuid_ids.append(UUID(fid) if isinstance(fid, str) else fid)
                        except ValueError:
                            continue

                    if uuid_ids:
                        result = await db.execute(
                            select(Document).where(Document.id.in_(uuid_ids))
                        )
                        docs = result.scalars().all()
                        doc_details = {str(doc.id): doc for doc in docs}
            except Exception as e:
                logger.warning(f"[AgentRuntime] 获取文档详情失败: {e}")

        # 添加源文档信息
        if context.file_ids:
            context_parts.append("\n\n## 用户已选择的文档（源文档）")
            for fid in context.file_ids:
                doc = doc_details.get(fid)
                if doc:
                    context_parts.append(f"- ID: {fid}")
                    context_parts.append(f"  文件名: {doc.original_filename}")
                    context_parts.append(f"  类型: {doc.file_type}")
                    context_parts.append(f"  分类: {doc.doc_category}")
                else:
                    context_parts.append(f"- ID: {fid}")
            context_parts.append("\n这些文档包含用户想要处理的数据。请根据需要查询这些文档的内容。")

        # 添加模板文档信息
        if context.template_id:
            context_parts.append("\n## 用户已选择的模板")
            doc = doc_details.get(context.template_id)
            if doc:
                context_parts.append(f"- ID: {context.template_id}")
                context_parts.append(f"  文件名: {doc.original_filename}")
                context_parts.append(f"  类型: {doc.file_type}")
            else:
                context_parts.append(f"- ID: {context.template_id}")
            context_parts.append("\n这是用户提供的表格模板，需要填入数据。")

        # 添加文件使用提示
        if context.file_ids or context.template_id:
            context_parts.append("\n## 文件使用提示")
            if context.file_ids:
                context_parts.append("- 源文档是用户指定的数据来源，必须优先使用这些文档")
                context_parts.append("- 不要询问用户选择了什么文档，直接使用上述文件信息")
            if context.template_id:
                context_parts.append("- 填表时必须使用指定的template_id作为输出目标")

        return "\n".join(context_parts) if context_parts else ""
