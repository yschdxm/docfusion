import json
import httpx
import logging
import re
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from app.core.config import get_settings
from app.core.rate_limiter import rate_limiter
from app.services.prompts import (
    NER_PROMPT,
    QUERY_GENERATION_PROMPT,
    ANSWER_EXTRACTION_PROMPT,
    SQL_GENERATION_PROMPT,
    ROW_FILL_PROMPT,
    BATCH_EXTRACT_PROMPT,
    FILL_SATISFACTION_PROMPT,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    def __init__(self):
        self.api_key = settings.MIMO_API_KEY
        self.base_url = settings.MIMO_BASE_URL
        self.model = settings.MIMO_MODEL
        self.ssl_verify = settings.SSL_VERIFY and settings.SSL_VERIFY_MIMO
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"LLMService初始化: model={self.model}, base_url={self.base_url}, ssl_verify={self.ssl_verify}")

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从 LLM 响应中鲁棒地提取 JSON。"""
        text = text.strip()

        # 1. ```json ... ``` 包裹
        json_block = re.search(r'```json\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if json_block:
            return json.loads(json_block.group(1).strip())

        # 2. ``` ... ``` 包裹（无 json 标签）
        code_block = re.search(r'```\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if code_block:
            return json.loads(code_block.group(1).strip())

        # 3. 平衡花括号匹配
        brace_start = text.find('{')
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[brace_start:i + 1])

        # 4. 平衡方括号匹配
        bracket_start = text.find('[')
        if bracket_start >= 0:
            depth = 0
            for i in range(bracket_start, len(text)):
                if text[i] == '[':
                    depth += 1
                elif text[i] == ']':
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[bracket_start:i + 1])

        # 5. 直接解析
        return json.loads(text)

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 65536,
        enable_thinking: bool = True,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto"
    ) -> Union[str, Dict[str, Any], AsyncGenerator[Dict[str, Any], None]]:
        """调用LLM聊天接口

        Args:
            messages: 对话消息列表
            temperature: 采样温度
            max_tokens: 最大token数
            enable_thinking: 是否启用思考模式 (MiMO原生)
            stream: 是否使用流式输出
            tools: 工具定义列表 (OpenAI格式)
            tool_choice: 工具选择策略

        Returns:
            如果stream=True: 返回AsyncGenerator
            如果stream=False且返回dict: 包含content, reasoning_content, tool_calls
            如果stream=False且返回str: 仅content (兼容旧代码)
        """
        import time

        start_time = time.time()
        logger.info(f"[llm_service.chat_completion] 开始调用 | model={self.model}, temperature={temperature}, max_tokens={max_tokens}, stream={stream}, enable_thinking={enable_thinking}")
        if tools:
            logger.info(f"[llm_service.chat_completion] 可用工具: {[t.get('function', {}).get('name', 'unknown') for t in tools]}")
        logger.debug(f"[llm_service.chat_completion] 消息数: {len(messages)}")

        # 构建请求体
        request_body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "thinking": {"type": "enabled" if enable_thinking else "disabled"},
            "stream": stream,
        }

        # 如果是流式输出，启用 usage 信息
        if stream:
            request_body["stream_options"] = {"include_usage": True}

        # 添加工具定义
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = tool_choice

        try:
            # 流控检查：预估 token 数量 (基于消息长度)
            estimated_tokens = sum(len(msg.get("content") or "") for msg in messages) // 4  # 粗略估算
            await rate_limiter.wait_for_permission(estimated_tokens)

            # 流式输出
            if stream:
                return self._chat_completion_stream(request_body, start_time, estimated_tokens)

            # 非流式输出
            async with httpx.AsyncClient(timeout=600.0, verify=self.ssl_verify) as client:
                logger.debug(f"[llm_service.chat_completion] 发送HTTP POST请求到 {self.base_url}/chat/completions")

                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=request_body
                )

                elapsed = time.time() - start_time
                logger.info(f"[llm_service.chat_completion] HTTP响应收到 | 状态码: {response.status_code} | 耗时: {elapsed:.2f}s")

                response.raise_for_status()
                result = response.json()

                # 检查响应结构
                if "choices" not in result:
                    logger.error(f"[llm_service.chat_completion] 响应缺少choices字段: {result.keys()}")
                    raise ValueError("LLM响应格式错误: 缺少choices字段")

                if not result["choices"]:
                    logger.error("[llm_service.chat_completion] choices为空列表")
                    raise ValueError("LLM响应格式错误: choices为空")

                message = result["choices"][0]["message"]
                content = message.get("content", "")
                reasoning_content = message.get("reasoning_content", "")
                tool_calls = message.get("tool_calls") or []
                total_time = time.time() - start_time

                # 记录实际 token 使用量
                usage = result.get("usage", {})
                actual_tokens = usage.get("total_tokens", estimated_tokens)
                await rate_limiter.record_request(actual_tokens)

                logger.info(f"[llm_service.chat_completion] 成功 | 内容长度: {len(content)}, 思考长度: {len(reasoning_content)}, 工具调用数: {len(tool_calls)} | 总耗时: {total_time:.2f}s | Token使用: {actual_tokens}")

                # 详细诊断日志：当 content 为空时记录完整响应结构
                if not content:
                    logger.warning(f"[llm_service.chat_completion] content 为空! 完整消息字段: {list(message.keys())}")
                    logger.warning(f"[llm_service.chat_completion] reasoning_content 长度: {len(reasoning_content)}")
                    if reasoning_content:
                        logger.warning(f"[llm_service.chat_completion] reasoning_content 前200字符: {reasoning_content[:200]}")
                        # 检查 reasoning_content 是否包含 JSON
                        if "{" in reasoning_content or "[" in reasoning_content:
                            logger.warning("[llm_service.chat_completion] reasoning_content 包含 JSON 结构")
                            # 记录 reasoning_content 的最后1000字符，看看是否有 JSON
                            logger.warning(f"[llm_service.chat_completion] reasoning_content 最后1000字符: {reasoning_content[-1000:]}")
                    # 记录完整的 message 结构（前1000字符）
                    import json
                    try:
                        msg_str = json.dumps(message, ensure_ascii=False, indent=2)
                        logger.warning(f"[llm_service.chat_completion] 完整消息结构: {msg_str[:1000]}...")
                    except Exception as e:
                        logger.warning(f"[llm_service.chat_completion] 无法序列化消息: {e}")

                if tool_calls:
                    logger.info(f"[llm_service.chat_completion] 工具调用: {[tc.get('function', {}).get('name', 'unknown') for tc in tool_calls]}")

                # 如果提供了工具但没有tool_calls，返回完整dict
                if tools:
                    return {
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "tool_calls": tool_calls,
                    }

                # 兼容旧代码：返回str
                return content

        except httpx.TimeoutException as e:
            total_time = time.time() - start_time
            logger.error(f"[llm_service.chat_completion] 请求超时 | 耗时: {total_time:.2f}s | error: {e}")
            raise
        except httpx.HTTPStatusError as e:
            total_time = time.time() - start_time
            logger.error(f"[llm_service.chat_completion] HTTP错误 | 状态码: {e.response.status_code} | 耗时: {total_time:.2f}s | error: {e}")
            logger.error(f"[llm_service.chat_completion] 错误响应: {e.response.text[:500]}")
            raise
        except Exception as e:
            total_time = time.time() - start_time
            logger.exception(f"[llm_service.chat_completion] 异常 | 耗时: {total_time:.2f}s | error: {e}")
            raise

    async def _chat_completion_stream(
        self,
        request_body: Dict[str, Any],
        start_time: float,
        estimated_tokens: int = 0
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式调用LLM

        Yields:
            包含 content, reasoning_content, tool_calls, finish_reason 的字典
        """
        import time
        logger.debug("[llm_service._chat_completion_stream] 开始流式调用")

        try:
            async with httpx.AsyncClient(timeout=600.0, verify=self.ssl_verify) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=request_body,
                ) as response:
                    response.raise_for_status()

                    actual_tokens = estimated_tokens
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(data)

                                # 检查是否有 usage 信息 (通常在最后一个 chunk)
                                if "usage" in chunk and chunk["usage"] is not None:
                                    usage = chunk["usage"]
                                    actual_tokens = usage.get("total_tokens", estimated_tokens)
                                    logger.debug(f"[llm_service._chat_completion_stream] 收到 usage 信息: {actual_tokens} tokens")
                                    continue

                                if "choices" not in chunk or not chunk["choices"]:
                                    continue

                                delta = chunk["choices"][0].get("delta", {})
                                finish_reason = chunk["choices"][0].get("finish_reason")

                                yield {
                                    "content": delta.get("content", ""),
                                    "reasoning_content": delta.get("reasoning_content", ""),
                                    "tool_calls": delta.get("tool_calls", []),
                                    "finish_reason": finish_reason,
                                }

                                # 如果是 stop 或 content_filter，可以结束流
                                # 但如果是 length，可能还有内容在后续 chunk 中（虽然不太可能）
                                # 这里保持原有逻辑，但增加日志
                                if finish_reason:
                                    logger.debug(f"[llm_service._chat_completion_stream] 收到finish_reason={finish_reason}，结束流")
                                    break

                            except json.JSONDecodeError:
                                logger.warning(f"[llm_service._chat_completion_stream] JSON解析失败: {data[:200]}")
                                continue

                    # 记录流式调用的 token 使用量
                    await rate_limiter.record_request(actual_tokens)

                    elapsed = time.time() - start_time
                    logger.info(f"[llm_service._chat_completion_stream] 流式调用完成 | 耗时: {elapsed:.2f}s | Token使用: {actual_tokens}")

        except Exception as e:
            logger.exception(f"[llm_service._chat_completion_stream] 流式调用异常: {e}")
            raise

    # ──────────────────────────── 实体关系提取 ────────────────────────────

    async def extract_entities_and_relations(
        self,
        text: str,
    ) -> Dict[str, Any]:
        """使用 100+ 实体类型 NER 提示词提取实体和关系。

        Returns:
            {"entities": [...], "relations": [...]}
        """
        prompt = NER_PROMPT.format(text=text[:80000])

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)

        try:
            result = self._extract_json(response)
            if isinstance(result, dict):
                entities = result.get("entities", [])
                relations = result.get("relations", [])
                # 添加详细日志
                logger.info("[NER-EXTRACT] 提取到 %d 个实体, %d 个关系", len(entities), len(relations))
                for i, e in enumerate(entities[:5]):  # 只显示前5个
                    attrs = e.get("attributes", {})
                    logger.info("[NER-EXTRACT] 实体 %d: name=%s, type=%s, attributes=%s",
                               i+1, e.get("name", "N/A"), e.get("type", "N/A"), attrs if attrs else "无")
                if len(entities) > 5:
                    logger.info("[NER-EXTRACT] ... 还有 %d 个实体", len(entities) - 5)
                return {"entities": entities, "relations": relations}
            elif isinstance(result, list):
                # 有些情况下返回的是实体列表
                logger.info("[NER-EXTRACT] LLM返回列表格式, %d 个条目", len(result))
                return {"entities": result, "relations": []}
            else:
                logger.warning("[NER-EXTRACT] 未知返回格式: %s", type(result))
                return {"entities": [], "relations": []}
        except json.JSONDecodeError as e:
            logger.error(f"NER JSON解析失败: response={response[:200]}, error={e}")
            return {"entities": [], "relations": []}
        except Exception as e:
            logger.error(f"NER异常: error={e}")
            return {"entities": [], "relations": []}

    # ──────────────────────────── 表格填写相关 ────────────────────────────

    async def generate_search_queries(
        self,
        field_name: str,
        row_context: str = "",
        table_headers: str = "",
    ) -> List[str]:
        """从字段名+行上下文生成搜索查询。

        Returns:
            ["query1", "query2", "query3"]
        """
        prompt = QUERY_GENERATION_PROMPT.format(
            field_name=field_name,
            row_context=row_context,
            table_headers=table_headers,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=1000)

        try:
            result = self._extract_json(response)
            return result.get("queries", [field_name])
        except Exception:
            return [field_name]

    async def extract_answer_from_context(
        self,
        query: str,
        field_name: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """从检索到的上下文中提取答案。

        Returns:
            {"answer": str|None, "confidence": float, "source": str}
        """
        context_text = "\n---\n".join(contexts[:5])
        prompt = ANSWER_EXTRACTION_PROMPT.format(
            query=query,
            field_name=field_name,
            context_text=context_text,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            return self._extract_json(response)
        except Exception:
            return {"answer": None, "confidence": 0.0, "source": "解析失败"}

    async def generate_sql(self, schema_info: str, question: str) -> Dict[str, Any]:
        """根据表结构信息生成 SQL 查询。

        Returns:
            {"sql": str, "explanation": str}
        """
        prompt = SQL_GENERATION_PROMPT.format(
            schema_info=schema_info,
            query=question,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            return self._extract_json(response)
        except Exception:
            return {"sql": "", "explanation": "SQL 生成失败"}

    async def extract_row_answers(
        self,
        table_headers: str,
        row_context: str,
        empty_fields: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """行级批量提取：一次 LLM 调用填写一行中所有空字段。

        Returns:
            {"answers": {"字段名": "值"|null, ...}, "confidence": float}
        """
        context_text = "\n---\n".join(contexts[:5])
        prompt = ROW_FILL_PROMPT.format(
            table_headers=table_headers,
            row_context=row_context,
            empty_fields=empty_fields,
            context_text=context_text,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            return self._extract_json(response)
        except Exception:
            return {"answers": {}, "confidence": 0.0}

    async def batch_extract_records(
        self,
        table_headers: str,
        contexts: List[str],
        table_context: str = "",
        document_title: str = "",
    ) -> List[Dict[str, str]]:
        """从源文档中批量提取所有符合表头结构的记录。

        Returns:
            [{"字段名1": "值1", "字段名2": "值2", ...}, ...]
        """
        context_text = "\n---\n".join(contexts[:5])
        prompt = BATCH_EXTRACT_PROMPT.format(
            table_headers=table_headers,
            context_text=context_text,
            table_context=table_context or "无",
            document_title=document_title if document_title else "未指定",
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=16000)
        logger.debug("[BATCH-EXTRACT] LLM响应长度: %d", len(response) if response else 0)

        try:
            result = self._extract_json(response)
            records = result.get("records", [])
            logger.debug("[BATCH-EXTRACT] 解析成功: %d 条记录", len(records))
            return records
        except Exception as e:
            logger.warning("[BATCH-EXTRACT] JSON解析失败: %s, response前200字: %s", e, response[:200] if response else "None")
            return []

    async def map_columns(
        self,
        template_headers: List[str],
        db_columns: List[str],
    ) -> Dict[str, str]:
        """用 AI 建立模板表头到数据库列名的映射。

        Returns:
            {"模板表头": "数据库列名", ...}
        """
        prompt = f"""请建立模板表头和数据库列名之间的映射关系。

模板表头：{template_headers}
数据库列名：{db_columns}

要求：
1. 每个模板表头对应一个数据库列名
2. 如果名称有差异但含义相同（如 PM2.5监测值 和 PM2_5监测值），建立映射
3. 如果找不到对应关系，不返回该表头

输出格式（JSON）：
{{"模板表头1": "数据库列名1", "模板表头2": "数据库列名2"}}

只返回JSON，不要其他说明。"""
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.1, max_tokens=1000)
        try:
            return self._extract_json(response)
        except Exception:
            return {}

    # ──────────────────────────── 分阶段填表相关 ────────────────────────────

    async def check_fill_satisfaction(
        self,
        table_headers: List[str],
        filled_rows: List[List[Any]],
        total_rows: int,
        source_type: str,
        raw_data_count: int,
        document_title: str = "",
    ) -> Dict[str, Any]:
        """让LLM判断当前填写结果是否满足要求。

        Returns:
            {"is_satisfied": bool, "reason": str, "missing_fields": [...], "suggestions": str, "decision": str}
        """
        # 计算统计信息
        data_rows = len(filled_rows) - 1 if len(filled_rows) > 0 else 0  # 排除表头
        filled_count = 0
        for row in filled_rows[1:]:  # 跳过表头
            if any(str(cell).strip() for cell in row if cell is not None):
                filled_count += 1

        # 准备示例行（最多5行）
        sample_rows = []
        for i, row in enumerate(filled_rows[:6]):  # 表头+前5行数据
            if i == 0:
                sample_rows.append(f"[表头] {row}")
            else:
                sample_rows.append(f"[行{i}] {row}")
        sample_text = "\n".join(sample_rows)

        headers_str = "，".join([h for h in table_headers if h])

        prompt = FILL_SATISFACTION_PROMPT.format(
            table_headers=headers_str,
            total_rows=total_rows,
            data_rows=data_rows,
            filled_rows=filled_count,
            sample_rows=sample_text,
            source_type=source_type,
            raw_data_count=raw_data_count,
            document_title=document_title if document_title else "未指定",
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            result = self._extract_json(response)
            return {
                "is_satisfied": result.get("is_satisfied", False),
                "reason": result.get("reason", ""),
                "missing_fields": result.get("missing_fields", []),
                "suggestions": result.get("suggestions", ""),
                "decision": result.get("decision", "continue"),
            }
        except Exception as e:
            logger.warning("[CHECK-SATISFACTION] JSON解析失败: %s, response: %s", e, response[:200] if response else "None")
            return {
                "is_satisfied": False,
                "reason": "LLM判断结果解析失败",
                "missing_fields": [],
                "suggestions": "请重试或检查数据源",
                "decision": "continue",
            }

    async def extract_records_from_graph(
        self,
        table_headers: str,
        graph_results: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """从图谱查询结果中提取结构化记录。

        Returns:
            [{"字段名1": "值1", "字段名2": "值2", ...}, ...]
        """
        if not graph_results:
            return []

        # 构建图谱结果文本
        result_texts = []
        for i, r in enumerate(graph_results[:20]):  # 最多20条
            content = r.get("content", "")
            if content:
                result_texts.append(f"{i+1}. {content}")

        if not result_texts:
            return []

        prompt = f"""从知识图谱查询结果中提取符合表格结构的结构化数据记录。

表格表头：{table_headers}

图谱查询结果：
{chr(10).join(result_texts)}

请从上述图谱结果中提取数据记录，每个记录的字段名必须与表头对应。
注意：
1. 只返回能从图谱结果中明确提取的数据
2. 如果某字段在图谱中找不到对应信息，该字段留空
3. 确保提取的数据格式正确

输出格式（JSON）：
{{"records": [
  {{"表头1": "值1", "表头2": "值2", ...}},
  {{"表头1": "值3", "表头2": "值4", ...}}
]}}

只返回JSON，不要其他说明。"""

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=8000)

        try:
            result = self._extract_json(response)
            records = result.get("records", [])
            logger.debug("[EXTRACT-FROM-GRAPH] 提取到 %d 条记录", len(records))
            return records
        except Exception as e:
            logger.warning("[EXTRACT-FROM-GRAPH] JSON解析失败: %s, response: %s", e, response[:200] if response else "None")
            return []

    # ──────────────────────────── 文档操作 ────────────────────────────

    async def document_operation(
        self,
        document_content: str,
        instruction: str,
        document_type: str
    ) -> Dict[str, Any]:
        prompt = f"""你是一个文档智能助手。根据用户的自然语言指令，对文档内容进行操作。

文档类型：{document_type}

文档内容：
{document_content[:80000]}

用户指令：
{instruction}

请执行用户的指令并返回结果。返回格式：
```json
{{
    "operation_type": "操作类型（extract/edit/format/convert/query）",
    "result": "操作结果或提取的内容",
    "success": true/false,
    "message": "操作说明"
}}
```

只返回JSON，不要其他说明。"""

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)

        try:
            return self._extract_json(response)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: response={response[:200]}, error={e}")
            return {"operation_type": "query", "result": response, "success": False, "message": "响应解析失败"}
        except Exception as e:
            logger.error(f"响应处理异常: error={e}")
            return {"operation_type": "query", "result": response, "success": False, "message": "响应处理异常"}


llm_service = LLMService()
