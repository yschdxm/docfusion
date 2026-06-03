import asyncio
import json
import httpx
import logging
import re
import time
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from app.core.config import get_settings
from app.core.rate_limiter import rate_limiter
from app.core.llm_errors import (
    LLMError,
    LLMErrorCode,
    LLMFinishReason,
    handle_http_error,
    handle_finish_reason,
    handle_response_validation_error,
    llm_error_logger,
)
from app.services.prompts import (
    NER_PROMPT,
    QUERY_GENERATION_PROMPT,
    ANSWER_EXTRACTION_PROMPT,
    SQL_GENERATION_PROMPT,
    ROW_FILL_PROMPT,
    BATCH_EXTRACT_PROMPT,
    FILL_SATISFACTION_PROMPT,
    REWRITE_PROMPT,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    """LLM 服务类 - 集成 MiMO API 错误处理"""

    # 可重试的错误代码
    RETRYABLE_ERRORS = {
        LLMErrorCode.RATE_LIMIT_ERROR,
        LLMErrorCode.SERVER_ERROR,
        LLMErrorCode.SERVICE_UNAVAILABLE,
        LLMErrorCode.GATEWAY_TIMEOUT,
        LLMErrorCode.TIMEOUT_ERROR,
        LLMErrorCode.CONNECTION_ERROR,
    }

    def __init__(self):
        # 初始化为空配置，等待数据库配置
        self.current_provider = ""
        self.api_key = ""
        self.base_url = ""
        self.model = ""
        self.max_output_tokens = 0
        self.max_context_tokens = 0
        self.ssl_verify = settings.SSL_VERIFY
        self.headers = {}
        self.max_retries = 3
        self.retry_delay = 1.0  # 初始重试延迟（秒）
        self.error_logger = llm_error_logger
        self._db_config_applied = False  # 标记是否已应用数据库配置
        self._configured = False  # 标记是否已配置
        self._model_lock = asyncio.Lock()  # 保护模型切换和LLM调用的原子性

        logger.info("LLMService初始化: 等待数据库配置")

    def update_config(self, api_key: str, base_url: str, model: str,
                      max_context_tokens: int = 128000, max_output_tokens: int = 4096) -> Dict[str, str]:
        """更新LLM配置

        Args:
            api_key: API密钥
            base_url: API地址
            model: 模型名称
            max_context_tokens: 上下文长度
            max_output_tokens: 最大输出长度

        Returns:
            包含当前模型信息的字典
        """
        if not api_key:
            raise ValueError("API Key 未配置")
        if not base_url:
            raise ValueError("Base URL 未配置")
        if not model:
            raise ValueError("Model 未配置")

        self.current_provider = "openai_compatible"
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self.ssl_verify = settings.SSL_VERIFY

        # 更新 headers
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        self._configured = True
        logger.info("LLM配置已更新: model=%s, base_url=%s", self.model, self.base_url)

        return {
            "provider": self.current_provider,
            "model": self.model,
            "base_url": self.base_url
        }

    def get_model_info(self) -> Dict[str, str]:
        """获取当前模型信息"""
        return {
            "provider": self.current_provider,
            "model": self.model,
            "base_url": self.base_url,
            "max_output_tokens": self.max_output_tokens,
            "max_context_tokens": self.max_context_tokens,
        }

    async def ensure_user_model(self, user_selected_model: str, db) -> bool:
        """确保当前配置为指定用户的模型（每次请求前调用）

        Args:
            user_selected_model: 用户的 selected_model 字段
            db: 数据库会话

        Returns:
            bool: 是否成功配置

        Raises:
            ValueError: 用户未选择模型
        """
        if not user_selected_model:
            raise ValueError("请先在左下角选择一个模型")

        # 如果当前已配置且模型匹配，直接返回
        if self._configured and self.model == user_selected_model:
            return True

        # 需要切换到用户选择的模型，从数据库查找配置
        from app.services.config_service import config_service
        import json as json_lib

        configs = await config_service.get_all(db)
        config_map = {c.key: c.value for c in configs}

        providers_json = config_map.get('llm_providers', '')
        if not providers_json:
            raise ValueError("系统未配置任何LLM供应商")

        try:
            providers = json_lib.loads(providers_json)
        except json_lib.JSONDecodeError:
            raise ValueError("LLM供应商配置格式错误")

        for provider in providers:
            provider_id = provider.get('id', '')
            api_key = provider.get('api_key', '')
            base_url = provider.get('base_url', '')

            if not api_key or not base_url:
                continue

            ctx_key = f'llm_{provider_id}_{user_selected_model}_max_context_tokens'
            out_key = f'llm_{provider_id}_{user_selected_model}_max_output_tokens'

            if ctx_key in config_map and out_key in config_map:
                max_context_tokens = config_map.get(ctx_key, '')
                max_output_tokens = config_map.get(out_key, '')

                if not max_context_tokens or not max_output_tokens:
                    continue

                self.update_config(
                    api_key=api_key,
                    base_url=base_url,
                    model=user_selected_model,
                    max_context_tokens=int(max_context_tokens),
                    max_output_tokens=int(max_output_tokens),
                )
                return True

        raise ValueError(f"未找到模型 {user_selected_model} 的配置，可能已被管理员删除")

    async def apply_db_config(self, db) -> bool:
        """从数据库应用配置（供应商+模型分离格式）

        Returns:
            bool: 是否成功配置（数据库中有有效的模型配置）
        """
        from app.services.config_service import config_service
        from app.models.user import User
        import json as json_lib

        # 获取所有配置
        configs = await config_service.get_all(db)
        config_map = {c.key: c.value for c in configs}

        # 解析供应商列表
        providers_json = config_map.get('llm_providers', '')
        if not providers_json:
            logger.warning("LLM配置不完整，请在管理中心配置至少一个LLM供应商")
            return False

        try:
            providers = json_lib.loads(providers_json)
        except json_lib.JSONDecodeError:
            logger.warning("LLM供应商配置格式错误")
            return False

        if not providers:
            logger.warning("LLM配置不完整，请在管理中心配置至少一个LLM供应商")
            return False

        # 获取用户的selected_model作为启动时的默认选择
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.selected_model.isnot(None)).limit(1))
        user_with_selection = result.scalar_one_or_none()
        preferred_model = user_with_selection.selected_model if user_with_selection else None

        # 遍历所有供应商和模型，查找匹配的配置
        for provider in providers:
            provider_id = provider.get('id', '')
            api_key = provider.get('api_key', '')
            base_url = provider.get('base_url', '')

            if not api_key or not base_url:
                continue

            # 查找该供应商下的所有模型
            prefix = f'llm_{provider_id}_'
            for key in config_map:
                if key.startswith(prefix) and key.endswith('_max_context_tokens'):
                    model_name = key[len(prefix):-len('_max_context_tokens')]
                    if not model_name:
                        continue

                    # 如果有用户偏好且匹配，或者没有偏好则使用第一个可用的
                    if preferred_model and model_name != preferred_model:
                        continue

                    max_context_tokens = config_map.get(f'{prefix}{model_name}_max_context_tokens', '')
                    max_output_tokens = config_map.get(f'{prefix}{model_name}_max_output_tokens', '')

                    # 上下文长度和最大输出长度为必填项，未填写则跳过该模型
                    if not max_context_tokens or not max_output_tokens:
                        continue

                    self.current_provider = "openai_compatible"
                    self.api_key = api_key
                    self.base_url = base_url
                    self.model = model_name
                    self.max_context_tokens = int(max_context_tokens)
                    self.max_output_tokens = int(max_output_tokens)
                    self.ssl_verify = settings.SSL_VERIFY
                    self.headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                    self._db_config_applied = True
                    self._configured = True
                    logger.info("LLM配置已从数据库应用: model=%s, base_url=%s", self.model, self.base_url)
                    return True

        # 如果没有匹配的用户偏好，使用第一个可用的供应商和模型
        for provider in providers:
            provider_id = provider.get('id', '')
            api_key = provider.get('api_key', '')
            base_url = provider.get('base_url', '')

            if not api_key or not base_url:
                continue

            prefix = f'llm_{provider_id}_'
            for key in config_map:
                if key.startswith(prefix) and key.endswith('_max_context_tokens'):
                    model_name = key[len(prefix):-len('_max_context_tokens')]
                    if not model_name:
                        continue

                    max_context_tokens = config_map.get(f'{prefix}{model_name}_max_context_tokens', '')
                    max_output_tokens = config_map.get(f'{prefix}{model_name}_max_output_tokens', '')

                    # 上下文长度和最大输出长度为必填项，未填写则跳过该模型
                    if not max_context_tokens or not max_output_tokens:
                        continue

                    self.current_provider = "openai_compatible"
                    self.api_key = api_key
                    self.base_url = base_url
                    self.model = model_name
                    self.max_context_tokens = int(max_context_tokens)
                    self.max_output_tokens = int(max_output_tokens)
                    self.ssl_verify = settings.SSL_VERIFY
                    self.headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                    self._db_config_applied = True
                    self._configured = True
                    logger.info("LLM配置已从数据库应用(默认): model=%s, base_url=%s", self.model, self.base_url)
                    return True

        logger.warning("LLM配置不完整，请在管理中心配置至少一个LLM供应商")
        return False

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
        max_tokens: Optional[int] = None,
        enable_thinking: bool = True,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        user_selected_model: Optional[str] = None,
        db=None,
    ) -> Union[str, Dict[str, Any], AsyncGenerator[Dict[str, Any], None]]:
        """调用LLM聊天接口（带错误处理和重试机制）

        Args:
            messages: 对话消息列表
            temperature: 采样温度
            max_tokens: 最大token数
            enable_thinking: 是否启用思考模式 (MiMO原生)
            stream: 是否使用流式输出
            tools: 工具定义列表 (OpenAI格式)
            tool_choice: 工具选择策略
            user_selected_model: 用户选择的模型（传入时自动校验并锁定配置）
            db: 数据库会话（配合 user_selected_model 使用）

        Returns:
            如果stream=True: 返回AsyncGenerator
            如果stream=False且返回dict: 包含content, reasoning_content, tool_calls
            如果stream=False且返回str: 仅content (兼容旧代码)

        Raises:
            LLMError: 当API调用失败或响应异常时
        """
        # 如果指定了用户模型，加锁确保模型切换和LLM调用的原子性
        if user_selected_model:
            async with self._model_lock:
                if db:
                    await self.ensure_user_model(user_selected_model, db)
                else:
                    from app.db.postgres import async_session
                    async with async_session() as session:
                        await self.ensure_user_model(user_selected_model, session)
                return await self._do_chat_completion(
                    messages=messages, temperature=temperature, max_tokens=max_tokens,
                    enable_thinking=enable_thinking, stream=stream, tools=tools, tool_choice=tool_choice,
                )

        # 未指定用户模型，直接调用（兼容其他服务如知识图谱、SQL查询等）
        return await self._do_chat_completion(
            messages=messages, temperature=temperature, max_tokens=max_tokens,
            enable_thinking=enable_thinking, stream=stream, tools=tools, tool_choice=tool_choice,
        )

    async def _do_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_thinking: bool = True,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto"
    ) -> Union[str, Dict[str, Any], AsyncGenerator[Dict[str, Any], None]]:
        """内部实现：调用LLM聊天接口（带错误处理和重试机制）"""
        # 检查是否已配置
        if not self._configured:
            raise LLMError(
                error_code=LLMErrorCode.CONNECTION_ERROR,
                message="请先选择模型",
                http_status=None,
            )

        if max_tokens is None:
            max_tokens = self.max_output_tokens
        start_time = time.time()

        # 记录请求开始
        self.error_logger.log_request_start(
            model=self.model,
            messages_count=len(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            enable_thinking=enable_thinking,
            has_tools=bool(tools),
        )

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

        # 请求信息（用于错误日志）
        request_info = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "enable_thinking": enable_thinking,
            "message_count": len(messages),
        }

        last_error: Optional[LLMError] = None

        # 重试循环
        for attempt in range(self.max_retries):
            try:
                # 流控检查：预估 token 数量
                estimated_tokens = sum(len(msg.get("content") or "") for msg in messages) // 4
                await rate_limiter.wait_for_permission(estimated_tokens)

                # 流式输出
                if stream:
                    return self._chat_completion_stream(
                        request_body=request_body,
                        start_time=start_time,
                        estimated_tokens=estimated_tokens
                    )

                # 非流式输出
                return await self._chat_completion_non_stream(
                    request_body=request_body,
                    start_time=start_time,
                    estimated_tokens=estimated_tokens,
                    tools=tools,
                    request_info=request_info,
                )

            except LLMError as e:
                last_error = e
                duration_ms = (time.time() - start_time) * 1000

                # 判断是否可重试
                if e.details.retryable and attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)  # 指数退避

                    self.error_logger.log_retry_attempt(
                        model=self.model,
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        error_code=e.details.error_code.value,
                        wait_seconds=wait_time,
                    )

                    await self._sleep(wait_time)
                    continue
                else:
                    # 不可重试或已达到最大重试次数
                    self.error_logger.log_request_error(
                        error=e,
                        model=self.model,
                        duration_ms=duration_ms,
                        extra_info={"attempt": attempt + 1, "max_retries": self.max_retries},
                    )
                    raise

            except Exception as e:
                # 未预期的异常
                duration_ms = (time.time() - start_time) * 1000
                error = self._convert_to_llm_error(e, request_info)
                self.error_logger.log_request_error(
                    error=error,
                    model=self.model,
                    duration_ms=duration_ms,
                    extra_info={"attempt": attempt + 1, "unexpected": True},
                )
                raise error

        # 所有重试都失败了
        if last_error:
            raise last_error

        # 不应该到达这里
        raise self._create_unknown_error("所有重试都失败了", request_info)

    async def _chat_completion_non_stream(
        self,
        request_body: Dict[str, Any],
        start_time: float,
        estimated_tokens: int,
        tools: Optional[List[Dict[str, Any]]],
        request_info: Dict[str, Any],
    ) -> Union[str, Dict[str, Any]]:
        """非流式调用 LLM"""

        async with httpx.AsyncClient(timeout=600.0, verify=self.ssl_verify) as client:
            logger.debug("[llm_service] 发送HTTP POST请求到 %s/chat/completions", self.base_url)

            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=request_body
                )

                elapsed = time.time() - start_time
                logger.debug("[llm_service] HTTP响应收到 | 状态码: %d | 耗时: %.2fs", response.status_code, elapsed)

                # 检查 HTTP 错误
                if response.status_code >= 400:
                    error = handle_http_error(
                        status_code=response.status_code,
                        response_text=response.text,
                        request_info=request_info,
                    )
                    raise error

                result = response.json()

            except httpx.TimeoutException as e:
                error = self._create_timeout_error(str(e), request_info)
                raise error
            except httpx.HTTPStatusError as e:
                # 处理 429 速率限制错误
                if e.response.status_code == 429:
                    retry_after = None
                    try:
                        # 尝试从响应头获取 retry-after
                        retry_after_str = e.response.headers.get("retry-after")
                        if retry_after_str:
                            retry_after = float(retry_after_str)
                    except (ValueError, TypeError):
                        pass

                    # 使用流控模块处理 429
                    wait_time = await rate_limiter.handle_api_rate_limit(
                        retry_after=retry_after,
                        error_message=e.response.text[:500]
                    )

                    # 创建速率限制错误，标记为可重试
                    error = await rate_limiter.create_rate_limit_error(
                        retry_after=wait_time,
                        error_message=e.response.text[:500],
                        request_info=request_info
                    )
                    raise error

                error = handle_http_error(
                    status_code=e.response.status_code,
                    response_text=e.response.text,
                    request_info=request_info,
                )
                raise error
            except Exception as e:
                if isinstance(e, LLMError):
                    raise
                error = self._create_connection_error(str(e), request_info)
                raise error

        # 验证响应结构
        self._validate_response_structure(result, request_info)

        # 检查 finish_reason
        finish_reason = result["choices"][0].get("finish_reason")
        if finish_reason and finish_reason not in [LLMFinishReason.STOP.value, LLMFinishReason.TOOL_CALLS.value]:
            error = handle_finish_reason(finish_reason, result, request_info)
            if error:
                # 记录警告但不抛出异常（某些情况如 length 可以继续处理）
                if error.details.error_code == LLMErrorCode.MAX_LENGTH_REACHED:
                    logger.warning("[llm_service] 达到最大长度限制，结果可能不完整: %s", error.details.message)
                elif error.details.error_code == LLMErrorCode.REPETITION_DETECTED:
                    logger.warning("[llm_service] 检测到重复内容，生成被截断: %s", error.details.message)
                else:
                    raise error

        message = result["choices"][0]["message"]
        content = message.get("content", "")
        reasoning_content = message.get("reasoning_content", "")
        tool_calls = message.get("tool_calls") or []
        total_time = time.time() - start_time

        # 记录实际 token 使用量
        usage = result.get("usage", {})
        actual_tokens = usage.get("total_tokens", estimated_tokens)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens")
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens")

        await rate_limiter.record_request(actual_tokens)

        # 记录成功日志
        self.error_logger.log_request_success(
            model=self.model,
            duration_ms=total_time * 1000,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=actual_tokens,
            finish_reason=finish_reason,
            has_reasoning=bool(reasoning_content),
            has_tool_calls=bool(tool_calls),
        )

        # 记录详细 token 使用
        self.error_logger.log_token_usage(
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=actual_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
        )

        # 诊断：当 content 为空时记录警告
        if not content and not tool_calls:
            self._log_empty_content_warning(message, reasoning_content)

        # 如果提供了工具，返回完整 dict
        if tools:
            return {
                "content": content,
                "reasoning_content": reasoning_content,
                "tool_calls": tool_calls,
            }

        # 兼容旧代码：返回 str
        return content

    async def _chat_completion_stream(
        self,
        request_body: Dict[str, Any],
        start_time: float,
        estimated_tokens: int = 0
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式调用LLM（带错误处理）

        Yields:
            包含 content, reasoning_content, tool_calls, finish_reason 的字典
        """
        chunk_index = 0
        actual_tokens = estimated_tokens
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0
        reasoning_tokens = 0
        last_finish_reason = None
        request_info = {"model": self.model, "stream": True}

        try:
            async with httpx.AsyncClient(timeout=600.0, verify=self.ssl_verify) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=request_body,
                ) as response:
                    # 检查 HTTP 错误
                    if response.status_code >= 400:
                        response_text = ""
                        async for chunk in response.aiter_text():
                            response_text += chunk
                        error = handle_http_error(
                            status_code=response.status_code,
                            response_text=response_text,
                            request_info=request_info,
                        )
                        raise error

                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(data)

                                # 检查是否有 usage 信息
                                if "usage" in chunk and chunk["usage"] is not None:
                                    usage = chunk["usage"]
                                    actual_tokens = usage.get("total_tokens", estimated_tokens)
                                    prompt_tokens = usage.get("prompt_tokens", 0)
                                    completion_tokens = usage.get("completion_tokens", 0)
                                    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                                    reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
                                    continue

                                if "choices" not in chunk or not chunk["choices"]:
                                    continue

                                delta = chunk["choices"][0].get("delta", {})
                                finish_reason = chunk["choices"][0].get("finish_reason")

                                if finish_reason:
                                    last_finish_reason = finish_reason

                                # 记录流式 chunk（调试级别）
                                self.error_logger.log_stream_chunk(
                                    model=self.model,
                                    chunk_index=chunk_index,
                                    has_content=bool(delta.get("content")),
                                    has_reasoning=bool(delta.get("reasoning_content")),
                                    has_tool_calls=bool(delta.get("tool_calls")),
                                    finish_reason=finish_reason,
                                )

                                chunk_index += 1

                                yield {
                                    "content": delta.get("content", ""),
                                    "reasoning_content": delta.get("reasoning_content", ""),
                                    "tool_calls": delta.get("tool_calls", []),
                                    "finish_reason": finish_reason,
                                }

                                # 检查 finish_reason
                                if finish_reason and finish_reason not in [
                                    LLMFinishReason.STOP.value, LLMFinishReason.TOOL_CALLS.value
                                ]:
                                    error = handle_finish_reason(finish_reason, chunk, request_info)
                                    if error and error.details.error_code in [
                                        LLMErrorCode.CONTENT_FILTERED,
                                    ]:
                                        # 严重的错误需要抛出
                                        raise error

                            except json.JSONDecodeError:
                                logger.warning("[llm_service] JSON解析失败: %s", data[:200])
                                continue

            # 流结束后yield usage统计数据
            yield {
                "content": "",
                "reasoning_content": "",
                "tool_calls": [],
                "finish_reason": None,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": actual_tokens,
                    "cached_tokens": cached_tokens,
                    "reasoning_tokens": reasoning_tokens,
                }
            }

            # 流式调用完成
            elapsed = time.time() - start_time
            self.error_logger.log_stream_complete(
                model=self.model,
                duration_ms=elapsed * 1000,
                total_chunks=chunk_index,
                total_tokens=actual_tokens,
                finish_reason=last_finish_reason,
            )

            # 记录 token 使用量
            await rate_limiter.record_request(actual_tokens)

            # 流结束后检查 finish_reason - 如果是异常情况需要抛出错误
            if last_finish_reason and last_finish_reason not in [
                LLMFinishReason.STOP.value, LLMFinishReason.TOOL_CALLS.value
            ]:
                error = handle_finish_reason(last_finish_reason, None, request_info)
                if error:
                    # content_filter 和 repetition_truncation 应该抛出错误
                    # length 情况：如果内容为空也应该抛出错误
                    if error.details.error_code == LLMErrorCode.CONTENT_FILTERED:
                        logger.error("[llm_service] 内容被过滤，流式调用失败: %s", error.details.message)
                        raise error
                    elif error.details.error_code == LLMErrorCode.REPETITION_DETECTED:
                        logger.error("[llm_service] 检测到重复内容，流式调用被截断: %s", error.details.message)
                        raise error
                    elif error.details.error_code == LLMErrorCode.MAX_LENGTH_REACHED:
                        # length 错误：如果内容为空则抛出错误，否则记录警告
                        logger.warning("[llm_service] 达到最大长度限制: %s", error.details.message)
                        # 注意：流式调用不能在这里抛出错误，因为已经 yield 了部分内容
                        # 但我们会记录这个状态，让调用方知道内容可能不完整

        except LLMError:
            raise
        except httpx.TimeoutException as e:
            raise self._create_timeout_error(str(e), request_info)
        except Exception as e:
            if isinstance(e, LLMError):
                raise
            raise self._create_connection_error(str(e), request_info)

    def _validate_response_structure(
        self,
        result: Dict[str, Any],
        request_info: Dict[str, Any]
    ) -> None:
        """验证响应结构"""

        if "choices" not in result:
            error = handle_response_validation_error(
                validation_error="LLM响应格式错误: 缺少choices字段",
                raw_response=json.dumps(result, ensure_ascii=False),
                request_info=request_info,
            )
            raise error

        if not result["choices"]:
            error = handle_response_validation_error(
                validation_error="LLM响应格式错误: choices为空列表",
                raw_response=json.dumps(result, ensure_ascii=False),
                request_info=request_info,
            )
            raise error

        if "message" not in result["choices"][0]:
            error = handle_response_validation_error(
                validation_error="LLM响应格式错误: choices[0]缺少message字段",
                raw_response=json.dumps(result, ensure_ascii=False),
                request_info=request_info,
            )
            raise error

    def _log_empty_content_warning(
        self,
        message: Dict[str, Any],
        reasoning_content: str
    ) -> None:
        """记录 content 为空的警告"""

        logger.warning("[llm_service] content 为空! 完整消息字段: %s", list(message.keys()))
        logger.warning("[llm_service] reasoning_content 长度: %d", len(reasoning_content))

        if reasoning_content:
            logger.warning("[llm_service] reasoning_content 前200字符: %s", reasoning_content[:200])
            if "{" in reasoning_content or "[" in reasoning_content:
                logger.warning("[llm_service] reasoning_content 包含 JSON 结构")
                logger.warning("[llm_service] reasoning_content 最后1000字符: %s", reasoning_content[-1000:])

        try:
            msg_str = json.dumps(message, ensure_ascii=False, indent=2)
            logger.warning("[llm_service] 完整消息结构: %s...", msg_str[:1000])
        except Exception as e:
            logger.warning("[llm_service] 无法序列化消息: %s", e)

    def _convert_to_llm_error(self, exc: Exception, request_info: Dict[str, Any]) -> LLMError:
        """将异常转换为 LLMError"""

        if isinstance(exc, LLMError):
            return exc

        if isinstance(exc, httpx.TimeoutException):
            return self._create_timeout_error(str(exc), request_info)

        if isinstance(exc, httpx.HTTPStatusError):
            return handle_http_error(
                status_code=exc.response.status_code,
                response_text=exc.response.text,
                request_info=request_info,
            )

        if isinstance(exc, json.JSONDecodeError):
            return handle_response_validation_error(
                validation_error=f"JSON解析错误: {exc}",
                request_info=request_info,
            )

        return self._create_unknown_error(str(exc), request_info)

    def _create_timeout_error(self, message: str, request_info: Dict[str, Any]) -> LLMError:
        """创建超时错误"""
        from app.core.llm_errors import create_llm_error
        return create_llm_error(
            error_code=LLMErrorCode.TIMEOUT_ERROR,
            message=f"请求超时: {message}",
            request_info=request_info,
        )

    def _create_connection_error(self, message: str, request_info: Dict[str, Any]) -> LLMError:
        """创建连接错误"""
        from app.core.llm_errors import create_llm_error
        return create_llm_error(
            error_code=LLMErrorCode.CONNECTION_ERROR,
            message=f"连接错误: {message}",
            request_info=request_info,
        )

    def _create_unknown_error(self, message: str, request_info: Dict[str, Any]) -> LLMError:
        """创建未知错误"""
        from app.core.llm_errors import create_llm_error
        return create_llm_error(
            error_code=LLMErrorCode.UNKNOWN_ERROR,
            message=f"未知错误: {message}",
            request_info=request_info,
        )

    @staticmethod
    async def _sleep(seconds: float) -> None:
        """异步等待"""
        import asyncio
        await asyncio.sleep(seconds)

    # ──────────────────────────── 实体关系提取 ────────────────────────────

    async def extract_entities_and_relations(
        self,
        text: str,
    ) -> Dict[str, Any]:
        """使用 100+ 实体类型 NER 提示词提取实体和关系。"""
        prompt = NER_PROMPT.format(text=text[:80000])

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
        except LLMError as e:
            logger.error("[NER-EXTRACT] LLM调用失败: %s", e)
            return {"entities": [], "relations": [], "error": str(e)}

        try:
            result = self._extract_json(response)
            if isinstance(result, dict):
                entities = result.get("entities", [])
                relations = result.get("relations", [])
                logger.info("[NER-EXTRACT] 提取到 %d 个实体, %d 个关系", len(entities), len(relations))
                return {"entities": entities, "relations": relations}
            elif isinstance(result, list):
                logger.info("[NER-EXTRACT] LLM返回列表格式, %d 个条目", len(result))
                return {"entities": result, "relations": []}
            else:
                logger.warning("[NER-EXTRACT] 未知返回格式: %s", type(result))
                return {"entities": [], "relations": []}
        except json.JSONDecodeError as e:
            logger.error("[NER-EXTRACT] JSON解析失败: %s", e)
            return {"entities": [], "relations": [], "error": f"JSON解析失败: {e}"}
        except Exception as e:
            logger.error("[NER-EXTRACT] 异常: %s", e)
            return {"entities": [], "relations": [], "error": str(e)}

    # ──────────────────────────── 表格填写相关 ────────────────────────────

    async def generate_search_queries(
        self,
        field_name: str,
        row_context: str = "",
        table_headers: str = "",
    ) -> List[str]:
        """从字段名+行上下文生成搜索查询。"""
        prompt = QUERY_GENERATION_PROMPT.format(
            field_name=field_name,
            row_context=row_context,
            table_headers=table_headers,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            result = self._extract_json(response)
            return result.get("queries", [field_name])
        except LLMError as e:
            logger.warning("[SEARCH-QUERIES] LLM调用失败: %s，返回默认查询", e)
            return [field_name]
        except Exception as e:
            logger.warning("[SEARCH-QUERIES] 异常: %s，返回默认查询", e)
            return [field_name]

    async def extract_answer_from_context(
        self,
        query: str,
        field_name: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """从检索到的上下文中提取答案。"""
        context_text = "\n---\n".join(contexts[:5])
        prompt = ANSWER_EXTRACTION_PROMPT.format(
            query=query,
            field_name=field_name,
            context_text=context_text,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            return self._extract_json(response)
        except LLMError as e:
            logger.warning("[EXTRACT-ANSWER] LLM调用失败: %s", e)
            return {"answer": None, "confidence": 0.0, "source": "LLM调用失败", "error": str(e)}
        except Exception as e:
            logger.warning("[EXTRACT-ANSWER] 异常: %s", e)
            return {"answer": None, "confidence": 0.0, "source": "解析失败", "error": str(e)}

    async def generate_sql(self, schema_info: str, question: str) -> Dict[str, Any]:
        """根据表结构信息生成 SQL 查询。"""
        prompt = SQL_GENERATION_PROMPT.format(
            schema_info=schema_info,
            query=question,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            return self._extract_json(response)
        except LLMError as e:
            logger.warning("[GENERATE-SQL] LLM调用失败: %s", e)
            return {"sql": "", "explanation": f"SQL生成失败: {e}"}
        except Exception as e:
            logger.warning("[GENERATE-SQL] 异常: %s", e)
            return {"sql": "", "explanation": "SQL生成失败"}

    async def extract_row_answers(
        self,
        table_headers: str,
        row_context: str,
        empty_fields: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """行级批量提取：一次 LLM 调用填写一行中所有空字段。"""
        context_text = "\n---\n".join(contexts[:5])
        prompt = ROW_FILL_PROMPT.format(
            table_headers=table_headers,
            row_context=row_context,
            empty_fields=empty_fields,
            context_text=context_text,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            return self._extract_json(response)
        except LLMError as e:
            logger.warning("[ROW-FILL] LLM调用失败: %s", e)
            return {"answers": {}, "confidence": 0.0, "error": str(e)}
        except Exception as e:
            logger.warning("[ROW-FILL] 异常: %s", e)
            return {"answers": {}, "confidence": 0.0, "error": str(e)}

    async def batch_extract_records(
        self,
        table_headers: str,
        contexts: List[str],
        table_context: str = "",
        document_title: str = "",
        max_records: int = 100,
    ) -> List[Dict[str, str]]:
        """从源文档中批量提取所有符合表头结构的记录。"""
        # 使用所有可用的上下文，最多10个chunk
        context_text = "\n---\n".join(contexts[:10])
        prompt = BATCH_EXTRACT_PROMPT.format(
            table_headers=table_headers,
            context_text=context_text,
            table_context=table_context or "无",
            document_title=document_title if document_title else "未指定",
            max_records=max_records,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            logger.debug("[BATCH-EXTRACT] LLM响应长度: %d", len(response) if response else 0)

            result = self._extract_json(response)
            records = result.get("records", [])
            logger.debug("[BATCH-EXTRACT] 解析成功: %d 条记录", len(records))
            return records
        except LLMError as e:
            logger.warning("[BATCH-EXTRACT] LLM调用失败: %s", e)
            return []
        except Exception as e:
            logger.warning("[BATCH-EXTRACT] JSON解析失败: %s", e)
            return []

    async def map_columns(
        self,
        template_headers: List[str],
        db_columns: List[str],
    ) -> Dict[str, str]:
        """用 AI 建立模板表头到数据库列名的映射。"""
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

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.1,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            return self._extract_json(response)
        except LLMError as e:
            logger.warning("[MAP-COLUMNS] LLM调用失败: %s", e)
            return {}
        except Exception as e:
            logger.warning("[MAP-COLUMNS] 异常: %s", e)
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
        """让LLM判断当前填写结果是否满足要求。"""
        # 计算统计信息
        data_rows = len(filled_rows) - 1 if len(filled_rows) > 0 else 0
        filled_count = 0
        for row in filled_rows[1:]:
            if any(str(cell).strip() for cell in row if cell is not None):
                filled_count += 1

        # 准备示例行（最多5行）
        sample_rows = []
        for i, row in enumerate(filled_rows[:6]):
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

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )

            result = self._extract_json(response)
            return {
                "is_satisfied": result.get("is_satisfied", False),
                "reason": result.get("reason", ""),
                "missing_fields": result.get("missing_fields", []),
                "suggestions": result.get("suggestions", ""),
                "decision": result.get("decision", "continue"),
            }
        except LLMError as e:
            logger.warning("[CHECK-SATISFACTION] LLM调用失败: %s", e)
            return {
                "is_satisfied": False,
                "reason": f"LLM调用失败: {e}",
                "missing_fields": [],
                "suggestions": "请重试或检查数据源",
                "decision": "continue",
            }
        except Exception as e:
            logger.warning("[CHECK-SATISFACTION] JSON解析失败: %s", e)
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
        """从图谱查询结果中提取结构化记录。"""
        if not graph_results:
            return []

        # 构建图谱结果文本
        result_texts = []
        for i, r in enumerate(graph_results[:20]):
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

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )

            result = self._extract_json(response)
            records = result.get("records", [])
            logger.debug("[EXTRACT-FROM-GRAPH] 提取到 %d 条记录", len(records))
            return records
        except LLMError as e:
            logger.warning("[EXTRACT-FROM-GRAPH] LLM调用失败: %s", e)
            return []
        except Exception as e:
            logger.warning("[EXTRACT-FROM-GRAPH] JSON解析失败: %s", e)
            return []

    # ──────────────────────────── 文档操作 ────────────────────────────

    async def rewrite_paragraph_text(self, original_text: str, rewrite_instruction: str) -> str:
        """使用LLM重写段落文本"""
        prompt = REWRITE_PROMPT.format(
            original_text=original_text,
            rewrite_instruction=rewrite_instruction,
        )
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(
            messages,
            temperature=0.3,
            # max_tokens 使用模型默认值
            enable_thinking=False,
        )
        return response.strip()

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

        try:
            response = await self.chat_completion(
                messages,
                temperature=0.3,
                # max_tokens 使用模型默认值
                enable_thinking=False
            )
            return self._extract_json(response)
        except LLMError as e:
            logger.error("[DOCUMENT-OPERATION] LLM调用失败: %s", e)
            return {
                "operation_type": "query",
                "result": "",
                "success": False,
                "message": f"LLM调用失败: {e.details.suggested_action or str(e)}"
            }
        except json.JSONDecodeError as e:
            logger.error("[DOCUMENT-OPERATION] JSON解析失败: %s", e)
            return {
                "operation_type": "query",
                "result": "",
                "success": False,
                "message": "响应解析失败"
            }
        except Exception as e:
            logger.error("[DOCUMENT-OPERATION] 异常: %s", e)
            return {
                "operation_type": "query",
                "result": "",
                "success": False,
                "message": "响应处理异常"
            }


llm_service = LLMService()
