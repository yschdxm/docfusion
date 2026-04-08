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
from typing import AsyncGenerator, Dict, Any, List, Optional
from datetime import datetime
import asyncio

from app.agent.core.registry import ToolRegistry
from app.agent.core.executor import ToolExecutor
from app.agent.core.stream import StreamManager, AgentEventType, AgentEvent
from app.agent.core.tracker import StepTracker, StepType
from app.agent.base.tool import ToolContext

from app.services.llm_service import llm_service
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select


logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """你是一个智能文档处理助手，专注于帮助用户完成文档理解和表格填写任务。

## 工作原则
1. 分析用户需求，理解任务目标
2. 根据文档类型选择正确的数据源（重要！）
3. 确保数据填写完整，不遗漏任何信息
4. 完成任务后，向用户报告结果

## 文档类型与数据源对应关系（重要！必须遵循）

不同文档类型的数据存储位置不同，必须根据文档类型选择正确的工具：

### xlsx 文件
- **数据位置**: PostgreSQL 数据库
- **首选工具**: query_pg_database
- **备选工具**: query_knowledge_graph (PG无结果时)

### docx / md / txt 文件
- **数据位置**: Neo4j 知识图谱（实体关系数据）和向量数据库（RAG检索）
- **首选工具**: query_knowledge_graph
- **备选工具**: rag_search (Neo4j无结果时)
- **注意**: 这些文档的数据**不在PG中**，不要浪费多次重试在PG查询上

### 填表时的文档类型判断
- 源文档是 xlsx → 优先使用 query_pg_database
- 源文档是 docx/md/txt → 直接使用 query_knowledge_graph，跳过PG查询

## 数据查找优先级（根据文档类型选择）

### 对于 xlsx 源文档：
1. **PostgreSQL (query_pg_database)** - xlsx结构化数据，最准确
2. **Neo4j (query_knowledge_graph)** - PG无结果时使用
3. **RAG检索 (rag_search)** - 非结构化文本补充
4. **文档提取 (extract_from_documents)** - 最后手段

### 对于 docx/md/txt 源文档：
1. **Neo4j (query_knowledge_graph)** - 实体关系数据，必须优先使用
2. **RAG检索 (rag_search)** - 文本片段补充
3. **文档提取 (extract_from_documents)** - 最后手段
4. **注意**: 这些文档在PG中没有数据，不要尝试PG查询

## 查询失败处理策略（根据文档类型）

### xlsx 文档的查询失败处理：
1. 优化查询条件（LIKE模糊匹配、检查列名）
2. 再次调用 query_pg_database 重试
3. 多次优化后仍无结果，切换到 query_knowledge_graph

### docx/md/txt 文档的查询失败处理：
1. 直接使用 query_knowledge_graph 查询
2. 如果Neo4j返回结果不足，立即使用 rag_search 补充
3. 不要尝试PG查询（这些文档的数据不在PG中）

## 填表任务完整流程（重要）

当用户需要填写表格时（消息包含"填表"、"填写"、"fill"或提供了template_id）：

### 第一步：判断源文档类型并选择数据源
1. 检查源文档 file_ids 对应的文档类型
2. **如果是 xlsx 文档**：使用 query_pg_database 查询
3. **如果是 docx/md/txt 文档**：直接使用 query_knowledge_graph，跳过PG查询

### 第二步：获取表格结构
使用 get_table_structure 工具了解：
- 表格有多少列，列名是什么
- 表格的数据范围（如"空气质量监测数据"、"城市GDP排名"）
- **多表格文档：仔细阅读每个表格的 context 字段，理解每个表格对应哪个城市/地区**

### 第三步：填写表格

**重要：不要搬运数据！不要把 query_pg_database 返回的 records 数组原样传给 fill_table 的 data 参数。**

#### 源文档和模板都是 xlsx（推荐用 source_query 自动模式）：
1. 调用 fill_table(source_query={"doc_ids": [...], "query": "描述需要什么数据"}, template_id=模板ID)
   - 工具内部自动完成：查询 → 返回数据摘要供审核 → 确认后填入模板
   - LLM 只需描述需要什么数据，审核数据摘要是否正确
2. 检查返回的数据摘要（前10行、中间5行、末尾5行、列信息、空值统计等）
3. 如果摘要正确，确认填入；如果不足则调整 query 重试

#### 其他情况（源文档或模板不是 xlsx）：
1. 使用 query_pg_database / query_knowledge_graph 查询数据
2. 将查询结果作为 data 参数传给 fill_table
3. 必要时使用 rag_search 补充

### 第四步：数据完整性检查
1. **强制性检查（必须执行）**：
   - 已填行数是否与表格应有的规模匹配？
   - 文档标题是否暗示更多数据？（如"百强"应有约100行，"TOP50"应有50行）
   - **填写比例 < 80% 时必须继续查询**

2. 如果数据不充分，调整 source_query 的 query 参数重试：
   - 更换查询关键词
   - 扩大查询范围

3. 使用 fill_table(source_query=..., output_doc_id=xxx, fill_mode="append") 追加数据

### 第五步：报告结果
向用户报告：
- 共填写了多少行数据
- 预期应该有多少行（根据文档标题判断）
- 填写完整度百分比
- 数据来源说明
- 下载链接

## 多表格文档填写策略

当模板文档包含多个表格时：

### 识别表格用途
1. 使用 get_table_structure 后，分析每个表格的 context.preceding_text 字段
2. 通过表格前的段落文本理解该表格应该填什么数据
3. 查看表格的 row_count 和 sample_data，判断表格是否已有数据或空行

### 数据过滤与路由原则
- 严禁：将所有数据无脑依次填入每个表格
- 必须：先理解每个表格的用途，再按需过滤数据

### fill_mode 详解（关键）
fill_mode 是针对单个表格的操作，不是文档级别的：

**fill_mode="overwrite"**：清空【target_table_index 指定的表格】，填入新数据
- 清空该表格的所有现有数据行（保留表头）
- 用于：表格为空、只有表头、有占位空行、或需要替换旧数据
- 注意：这只会影响指定的表格，不会清空整个文档

**fill_mode="append"**：在【target_table_index 指定的表格】末尾添加新行
- 保留该表格的现有数据，在后面添加新行
- 用于：该表格已有有效数据，需要继续添加更多数据时
- 注意：这是针对同一个表格的追加，不是"跳到"下一个表格

常见误区纠正：
- ❌ 错误理解："表格1填完了，用 append 追加到表格2"
- ✅ 正确理解："表格2当前只有表头/空行，需要用 overwrite 清空后填入"

多表格填写流程：
```
1. 获取表格结构 → 发现多个表格
   - 分析每个表格的 context 了解其用途
   - 检查每个表格的状态：只有表头/空行 vs 已有有效数据

2. 查询所需数据

3. 填写表格0：
   - fill_mode="overwrite"（清空后填入）
   - target_table_index=0
   - 创建新文件

4. 填写表格1：
   - 检查表格1状态：如果只有表头/空行 → 用 overwrite；如果已有数据 → 用 append
   - output_doc_id=上一步返回的ID（继续填写同一个文件）
   - target_table_index=1（指定第二个表格）

5. 后续表格同理，每个独立判断 fill_mode
```

### target_table_index 使用
- 表格索引从0开始，按文档中出现顺序
- 多表格文档必须指定 target_table_index，否则可能填错位
- 每个表格独立判断 fill_mode，不要假设都用 append

## 增量填表示例流程
```
用户: "填写空气质量监测数据"

↓ 1. get_table_structure(template_id)
   → 获取表头: [城市, 区, 站点, AQI, PM10, PM2.5]

↓ 2. query_pg_database("查询环境空气质量监测数据")
   → 返回100条记录

↓ 3. fill_table(fill_mode="overwrite", data=100条)
   → 创建新文件，返回 output_file_id=doc-001
   → 已填100行

↓ 4. 评估：数据可能还有更多，继续查询

↓ 5. query_pg_database("查询更多空气质量监测数据")
   → 返回100条记录

↓ 6. fill_table(fill_mode="append", output_doc_id=doc-001, data=100条)
   → 追加到已有文件
   → 总计200行

↓ 7. 重复直到数据完整...

↓ 8. 报告用户："已完成表格填写，共填写500行数据，下载链接: xxx"
```

## 重要提醒
- 填表任务必须使用 fill_table 工具生成可下载的文档
- 增量填表时记住 output_file_id，后续追加需要传入 output_doc_id
- 只调用确实需要的工具
- 参数必须准确且完整
- 根据工具返回结果调整后续策略
- 如果工具调用失败，尝试其他方法或向用户说明问题
- 当PG查询失败时，优先优化查询条件而不是切换工具
"""


class AgentRuntime:
    """Agent运行时

    协调LLM调用和工具执行，支持流式输出。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        max_iterations: int = 30,
        max_tool_retries: int = 3
    ):
        self.registry = registry
        self.executor = ToolExecutor(registry)
        self.max_iterations = max_iterations
        self.max_tool_retries = max_tool_retries
        logger.info(f"[AgentRuntime] 初始化 | max_iterations={max_iterations}, max_tool_retries={max_tool_retries}")

    async def run(
        self,
        message: str,
        file_ids: List[str],
        template_id: Optional[str] = None,
        conversation_history: List[Dict[str, str]] = None,
        stream_manager: Optional[StreamManager] = None,
        step_tracker: Optional[StepTracker] = None
    ) -> Dict[str, Any]:
        """运行Agent（非流式）"""
        context = ToolContext(
            session_id=f"session_{datetime.utcnow().timestamp()}",
            file_ids=file_ids,
            template_id=template_id,
            conversation_history=conversation_history or []
        )

        logger.info("=" * 60)
        logger.info("[AgentRuntime.run] 任务开始")
        logger.info(f"[AgentRuntime.run] Session: {context.session_id}")
        logger.info(f"[AgentRuntime.run] 用户输入: {message[:100]}..." if len(message) > 100 else f"[AgentRuntime.run] 用户输入: {message}")
        logger.info(f"[AgentRuntime.run] file_ids={file_ids}, template_id={template_id}")
        logger.info("=" * 60)

        tracker = step_tracker or StepTracker()
        stream = stream_manager or StreamManager()

        try:
            result = await self._execute_loop(
                message=message,
                context=context,
                tracker=tracker,
                stream=stream
            )
            logger.info(f"[AgentRuntime.run] 任务完成 | success={result.get('success')}")
            return result
        except Exception as e:
            logger.exception(f"[AgentRuntime.run] 任务异常: {e}")
            await stream.emit_failed(str(e))
            return {"success": False, "error": str(e), "steps": tracker.to_dict()}

    async def run_stream(
        self,
        message: str,
        file_ids: List[str],
        template_id: Optional[str] = None,
        conversation_history: List[Dict[str, str]] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> AsyncGenerator[str, None]:
        """运行Agent（流式）

        Args:
            cancel_event: 取消事件，当设置时任务会被取消
        """
        stream = StreamManager()
        tracker = StepTracker()

        context = ToolContext(
            session_id=f"session_{datetime.utcnow().timestamp()}",
            file_ids=file_ids,
            template_id=template_id,
            conversation_history=conversation_history or []
        )

        logger.info("=" * 60)
        logger.info("[AgentRuntime.run_stream] 流式任务开始")
        logger.info(f"[AgentRuntime.run_stream] Session: {context.session_id}")
        logger.info(f"[AgentRuntime.run_stream] 用户输入: {message[:100]}..." if len(message) > 100 else f"[AgentRuntime.run_stream] 用户输入: {message}")
        logger.info("=" * 60)

        # 启动执行任务
        logger.debug("[AgentRuntime.run_stream] 创建执行task")
        task = asyncio.create_task(
            self._execute_loop(message, context, tracker, stream, cancel_event)
        )

        # 流式输出事件
        event_count = 0
        logger.info("[AgentRuntime.run_stream] 开始流式输出")
        try:
            async for event in stream.stream():
                event_count += 1
                yield event
                # 检查是否被取消
                if cancel_event and cancel_event.is_set():
                    logger.info("[AgentRuntime.run_stream] 检测到取消信号，停止流式输出")
                    break
        except Exception as e:
            logger.error(f"[AgentRuntime.run_stream] 流输出异常: {e}")
            raise

        logger.info(f"[AgentRuntime.run_stream] 流式输出结束 | 共{event_count}个事件")

        # 如果任务仍在运行，取消它
        if not task.done():
            logger.info("[AgentRuntime.run_stream] 取消执行task")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info("[AgentRuntime.run_stream] 任务已取消")
                if not stream.is_closed():
                    await stream.emit_cancelled("用户取消了任务")
                    yield AgentEvent(
                        event_type=AgentEventType.CANCELLED,
                        data={"message": "用户取消了任务"}
                    ).to_sse_format()
            except Exception as e:
                logger.exception(f"[AgentRuntime.run_stream] 取消task时异常: {e}")
        else:
            # 等待任务完成
            try:
                await task
                logger.info("[AgentRuntime.run_stream] 执行task完成")
            except Exception as e:
                logger.exception(f"[AgentRuntime.run_stream] 执行task异常: {e}")
                if not stream.is_closed():
                    await stream.emit_failed(str(e))
                    yield AgentEvent(
                        event_type=AgentEventType.FAILED,
                        data={"error": str(e)}
                    ).to_sse_format()

    async def _execute_loop(
        self,
        message: str,
        context: ToolContext,
        tracker: StepTracker,
        stream: StreamManager,
        cancel_event: Optional[asyncio.Event] = None
    ) -> Dict[str, Any]:
        """执行主循环 - 使用原生工具调用和流式输出"""
        logger.info("[AgentRuntime._execute_loop] 进入执行循环 (原生工具调用)")

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
        system_content = SYSTEM_PROMPT_TEMPLATE + user_context

        messages = [{"role": "system", "content": system_content}]
        messages.extend(context.conversation_history)
        messages.append({"role": "user", "content": message})

        logger.info(f"[AgentRuntime._execute_loop] 构建完成 | 消息数: {len(messages)}")

        final_result = None
        total_tool_calls = 0

        for iteration in range(self.max_iterations):
            # 检查是否被取消
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

                llm_stream = await llm_service.chat_completion(
                    messages=messages,
                    temperature=0.7,
                    max_tokens=64000,  # 使用模型的最大输出长度 64K
                    enable_thinking=True,
                    stream=True,
                    tools=openai_tools,
                )

                has_emitted_thinking_end = False
                has_emitted_content = False

                async for chunk in llm_stream:
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
                logger.info(f"[AgentRuntime._execute_loop] LLM流式调用完成 | 耗时: {response_time:.2f}s | 内容长度: {len(full_content)} | 思考长度: {len(full_reasoning)} | 工具调用: {len(tool_calls_buffer)}")

            except Exception as e:
                logger.exception(f"[AgentRuntime._execute_loop] LLM调用失败: {e}")
                tracker.fail_step(step.id, str(e))
                await stream.emit_error(f"LLM调用失败: {e}")
                return {"success": False, "error": str(e), "steps": tracker.to_dict()}

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

                    # 如果有思考内容，说明LLM完成了思考但没有生成最终回复（可能是任务已完成）
                    # 如果没有思考内容但刚执行完工具，也可能是任务已完成
                    # 如果都没有，才视为错误
                    if full_reasoning and full_reasoning.strip():
                        # 有思考内容但没有最终回复，说明LLM完成了任务但不需要回复
                        logger.info(f"[AgentRuntime._execute_loop] LLM完成任务但无最终回复（有思考内容），思考长度: {len(full_reasoning)}")
                        tracker.complete_step(step.id, {"response": "", "reasoning": full_reasoning, "note": "LLM完成任务但无最终回复"})
                        await stream.emit_completed("", {"final_response": "", "reasoning": full_reasoning, "note": "任务已完成"})
                        return {"success": True, "message": "", "reasoning": full_reasoning, "steps": tracker.to_dict()}
                    elif is_after_tool_result:
                        # 刚执行完工具，LLM没有回复内容，可能是任务已完成（如填表任务）
                        logger.info(f"[AgentRuntime._execute_loop] LLM在工具执行后无回复，可能是任务已完成")
                        tracker.complete_step(step.id, {"response": "", "reasoning": full_reasoning, "note": "任务已完成（工具执行后无回复）"})
                        await stream.emit_completed("", {"final_response": "", "reasoning": full_reasoning, "note": "任务已完成"})
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
                await stream.emit_completed(full_content, {"final_response": full_content, "reasoning": full_reasoning})
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
            for tool_call in tool_calls_buffer:
                tool_name = tool_call["function"]["name"]
                try:
                    tool_args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}
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
                    tracker.complete_step(
                        tool_step.id,
                        result=result.data if isinstance(result.data, dict) else {"data": result.data}
                    )
                    await stream.emit_tool_result(
                        tool_name=tool_name,
                        result=result.data if isinstance(result.data, dict) else {"data": str(result.data)},
                        execution_time_ms=result.execution_time_ms
                    )
                    await stream.emit_step_end(tool_step.id, "工具执行成功")
                else:
                    logger.error(f"[AgentRuntime._execute_loop] 工具 {tool_name} 失败 | 耗时: {tool_time:.2f}s | 错误: {result.error}")
                    tracker.fail_step(tool_step.id, result.error)
                    await stream.emit_tool_error(tool_name, result.error)
                    await stream.emit_step_end(tool_step.id, f"工具执行失败: {result.error}")

                # 添加工具调用和结果到对话历史
                messages.append({
                    "role": "assistant",
                    "content": full_content if full_content else None,
                    "tool_calls": [tool_call]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result.data, ensure_ascii=False) if result.success else result.error
                })
                logger.debug(f"[AgentRuntime._execute_loop] 已添加工具结果到对话历史 | 当前消息数: {len(messages)}")

                final_result = result

            logger.info(f"[AgentRuntime._execute_loop] 迭代 {iteration + 1} 完成 | 调用 {len(tool_calls_buffer)} 个工具")

        # 达到最大迭代次数
        logger.warning(f"[AgentRuntime._execute_loop] 达到最大迭代次数: {self.max_iterations}")
        await stream.emit_warning(f"达到最大迭代次数限制 ({self.max_iterations})")
        await stream.emit_completed(
            "任务已部分完成，但达到了最大迭代次数限制。",
            {"partial_result": final_result.data if final_result else None}
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
