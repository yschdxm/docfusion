"""LLM 错误处理模块 - 基于 MiMO API 文档设计

MiMO API 错误类型:
- finish_reason: stop, length, tool_calls, content_filter, repetition_truncation
- error_message: 联网搜索的错误信息
- HTTP 状态码错误 (4xx, 5xx)
- 超时错误
"""

import json
import logging
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class LLMFinishReason(str, Enum):
    """MiMO API finish_reason 枚举"""
    STOP = "stop"                          # 自然停止点
    LENGTH = "length"                      # 达到最大 token 数
    TOOL_CALLS = "tool_calls"              # 模型调用了工具
    CONTENT_FILTER = "content_filter"      # 触发过滤策略
    REPETITION_TRUNCATION = "repetition_truncation"  # 检测到复读


class LLMErrorCode(str, Enum):
    """LLM 错误代码枚举"""
    # API 级别错误
    AUTHENTICATION_ERROR = "authentication_error"      # 认证失败 (401)
    RATE_LIMIT_ERROR = "rate_limit_error"              # 速率限制 (429)
    QUOTA_EXCEEDED = "quota_exceeded"                  # 额度耗尽
    INVALID_REQUEST = "invalid_request"                # 请求参数错误 (400)
    NOT_FOUND = "not_found"                            # 资源不存在 (404)

    # 服务端错误
    SERVER_ERROR = "server_error"                      # 服务器内部错误 (500)
    SERVICE_UNAVAILABLE = "service_unavailable"        # 服务不可用 (503)
    GATEWAY_TIMEOUT = "gateway_timeout"                # 网关超时 (504)

    # 内容生成错误
    CONTENT_FILTERED = "content_filtered"              # 内容被过滤
    MAX_LENGTH_REACHED = "max_length_reached"          # 达到最大长度限制
    REPETITION_DETECTED = "repetition_detected"        # 检测到重复内容
    WEB_SEARCH_ERROR = "web_search_error"              # 联网搜索错误

    # 网络/连接错误
    TIMEOUT_ERROR = "timeout_error"                    # 请求超时
    CONNECTION_ERROR = "connection_error"              # 连接错误
    SSL_ERROR = "ssl_error"                            # SSL 验证错误

    # 响应解析错误
    INVALID_RESPONSE = "invalid_response"              # 响应格式错误
    JSON_DECODE_ERROR = "json_decode_error"            # JSON 解析错误
    MISSING_CHOICES = "missing_choices"                # 响应缺少 choices

    # 未知错误
    UNKNOWN_ERROR = "unknown_error"                    # 未知错误


@dataclass
class LLMErrorDetails:
    """LLM 错误详情数据类"""
    error_code: LLMErrorCode
    message: str
    http_status: Optional[int] = None
    finish_reason: Optional[LLMFinishReason] = None
    error_message: Optional[str] = None          # MiMO API 返回的 error_message
    raw_response: Optional[str] = None           # 原始响应内容
    request_info: Dict[str, Any] = field(default_factory=dict)  # 请求信息
    retryable: bool = False                      # 是否可重试
    suggested_action: Optional[str] = None       # 建议操作

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "http_status": self.http_status,
            "finish_reason": self.finish_reason.value if self.finish_reason else None,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "suggested_action": self.suggested_action,
        }


class LLMError(Exception):
    """LLM 基础异常类"""

    def __init__(self, details: LLMErrorDetails):
        self.details = details
        super().__init__(details.message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return self.details.to_dict()

    def __str__(self) -> str:
        parts = [f"[{self.details.error_code.value}] {self.details.message}"]
        if self.details.http_status:
            parts.append(f"HTTP Status: {self.details.http_status}")
        if self.details.finish_reason:
            parts.append(f"Finish Reason: {self.details.finish_reason.value}")
        if self.details.error_message:
            parts.append(f"API Error: {self.details.error_message}")
        return " | ".join(parts)


class LLMAuthenticationError(LLMError):
    """认证错误 (401)"""
    pass


class LLMRateLimitError(LLMError):
    """速率限制错误 (429)"""
    pass


class LLMQuotaExceededError(LLMError):
    """额度耗尽错误"""
    pass


class LLMContentFilterError(LLMError):
    """内容过滤错误"""
    pass


class LLMTimeoutError(LLMError):
    """超时错误"""
    pass


class LLMServerError(LLMError):
    """服务器错误 (5xx)"""
    pass


class LLMValidationError(LLMError):
    """请求验证错误 (400)"""
    pass


class LLMResponseError(LLMError):
    """响应解析错误"""
    pass


# 错误代码到异常类的映射
ERROR_CODE_TO_EXCEPTION = {
    LLMErrorCode.AUTHENTICATION_ERROR: LLMAuthenticationError,
    LLMErrorCode.RATE_LIMIT_ERROR: LLMRateLimitError,
    LLMErrorCode.QUOTA_EXCEEDED: LLMQuotaExceededError,
    LLMErrorCode.CONTENT_FILTERED: LLMContentFilterError,
    LLMErrorCode.TIMEOUT_ERROR: LLMTimeoutError,
    LLMErrorCode.SERVER_ERROR: LLMServerError,
    LLMErrorCode.SERVICE_UNAVAILABLE: LLMServerError,
    LLMErrorCode.GATEWAY_TIMEOUT: LLMServerError,
    LLMErrorCode.INVALID_REQUEST: LLMValidationError,
    LLMErrorCode.INVALID_RESPONSE: LLMResponseError,
    LLMErrorCode.JSON_DECODE_ERROR: LLMResponseError,
    LLMErrorCode.MISSING_CHOICES: LLMResponseError,
}


def create_llm_error(
    error_code: LLMErrorCode,
    message: str,
    http_status: Optional[int] = None,
    finish_reason: Optional[str] = None,
    error_message: Optional[str] = None,
    raw_response: Optional[str] = None,
    request_info: Optional[Dict[str, Any]] = None,
) -> LLMError:
    """创建适当的 LLMError 实例

    Args:
        error_code: 错误代码
        message: 错误消息
        http_status: HTTP 状态码
        finish_reason: MiMO API finish_reason
        error_message: MiMO API 返回的 error_message
        raw_response: 原始响应内容
        request_info: 请求信息

    Returns:
        LLMError 实例
    """
    # 解析 finish_reason
    parsed_finish_reason = None
    if finish_reason:
        try:
            parsed_finish_reason = LLMFinishReason(finish_reason)
        except ValueError:
            pass

    # 构建错误详情
    details = LLMErrorDetails(
        error_code=error_code,
        message=message,
        http_status=http_status,
        finish_reason=parsed_finish_reason,
        error_message=error_message,
        raw_response=raw_response,
        request_info=request_info or {},
        retryable=_is_retryable(error_code, http_status),
        suggested_action=_get_suggested_action(error_code, http_status),
    )

    # 获取对应的异常类
    exception_class = ERROR_CODE_TO_EXCEPTION.get(error_code, LLMError)
    return exception_class(details)


def _is_retryable(error_code: LLMErrorCode, http_status: Optional[int]) -> bool:
    """判断错误是否可重试"""
    # 可重试的错误代码
    retryable_codes = {
        LLMErrorCode.RATE_LIMIT_ERROR,
        LLMErrorCode.SERVER_ERROR,
        LLMErrorCode.SERVICE_UNAVAILABLE,
        LLMErrorCode.GATEWAY_TIMEOUT,
        LLMErrorCode.TIMEOUT_ERROR,
        LLMErrorCode.CONNECTION_ERROR,
    }

    if error_code in retryable_codes:
        return True

    # 根据 HTTP 状态码判断
    if http_status in [429, 500, 502, 503, 504]:
        return True

    return False


def _get_suggested_action(error_code: LLMErrorCode, http_status: Optional[int]) -> Optional[str]:
    """获取建议操作"""
    action_map = {
        LLMErrorCode.AUTHENTICATION_ERROR: "请检查 MIMO_API_KEY 是否配置正确",
        LLMErrorCode.RATE_LIMIT_ERROR: "请求过于频繁，请稍后重试",
        LLMErrorCode.QUOTA_EXCEEDED: "API 额度已耗尽，请联系管理员充值",
        LLMErrorCode.CONTENT_FILTERED: "输入内容触发过滤策略，请修改输入后重试",
        LLMErrorCode.TIMEOUT_ERROR: "请求超时，请稍后重试或减小请求内容",
        LLMErrorCode.CONNECTION_ERROR: "网络连接错误，请检查网络配置",
        LLMErrorCode.SERVER_ERROR: "MiMO 服务暂时不可用，请稍后重试",
        LLMErrorCode.INVALID_REQUEST: "请求参数错误，请检查输入",
        LLMErrorCode.MAX_LENGTH_REACHED: "达到最大长度限制，请减小 max_tokens 或输入内容",
        LLMErrorCode.WEB_SEARCH_ERROR: "联网搜索失败，请稍后重试或关闭联网搜索",
    }

    return action_map.get(error_code)


def handle_http_error(
    status_code: int,
    response_text: str,
    request_info: Optional[Dict[str, Any]] = None
) -> LLMError:
    """处理 HTTP 错误

    Args:
        status_code: HTTP 状态码
        response_text: 响应文本
        request_info: 请求信息

    Returns:
        LLMError 实例
    """
    # 尝试解析错误响应
    error_data = _parse_error_response(response_text)
    api_error_message = error_data.get("error", {}).get("message") if isinstance(error_data, dict) else None

    # 根据状态码映射错误
    status_code_map = {
        400: (LLMErrorCode.INVALID_REQUEST, "请求参数错误"),
        401: (LLMErrorCode.AUTHENTICATION_ERROR, "API 认证失败"),
        403: (LLMErrorCode.AUTHENTICATION_ERROR, "权限不足"),
        404: (LLMErrorCode.NOT_FOUND, "请求的资源不存在"),
        429: (LLMErrorCode.RATE_LIMIT_ERROR, "请求过于频繁，触发速率限制"),
        500: (LLMErrorCode.SERVER_ERROR, "MiMO 服务器内部错误"),
        502: (LLMErrorCode.SERVICE_UNAVAILABLE, "网关错误"),
        503: (LLMErrorCode.SERVICE_UNAVAILABLE, "服务暂时不可用"),
        504: (LLMErrorCode.GATEWAY_TIMEOUT, "网关超时"),
    }

    error_code, default_message = status_code_map.get(
        status_code,
        (LLMErrorCode.UNKNOWN_ERROR, f"未知 HTTP 错误 (状态码: {status_code})")
    )

    message = api_error_message or default_message

    return create_llm_error(
        error_code=error_code,
        message=message,
        http_status=status_code,
        error_message=api_error_message,
        raw_response=response_text[:2000] if response_text else None,
        request_info=request_info,
    )


def handle_finish_reason(
    finish_reason: str,
    response_data: Optional[Dict[str, Any]] = None,
    request_info: Optional[Dict[str, Any]] = None
) -> Optional[LLMError]:
    """处理 MiMO API finish_reason

    Args:
        finish_reason: finish_reason 值
        response_data: 完整响应数据
        request_info: 请求信息

    Returns:
        如果是异常情况返回 LLMError，否则返回 None
    """
    if finish_reason == LLMFinishReason.STOP.value:
        return None  # 正常停止

    if finish_reason == LLMFinishReason.TOOL_CALLS.value:
        return None  # 工具调用是正常行为

    # 获取 error_message（联网搜索错误等）
    error_message = None
    if response_data and "choices" in response_data:
        message = response_data["choices"][0].get("message", {})
        error_message = message.get("error_message")

    finish_reason_map = {
        LLMFinishReason.LENGTH.value: (
            LLMErrorCode.MAX_LENGTH_REACHED,
            "生成内容达到最大 token 限制，可能不完整"
        ),
        LLMFinishReason.CONTENT_FILTER.value: (
            LLMErrorCode.CONTENT_FILTERED,
            "内容触发过滤策略，生成被截断"
        ),
        LLMFinishReason.REPETITION_TRUNCATION.value: (
            LLMErrorCode.REPETITION_DETECTED,
            "检测到重复内容，生成被截断"
        ),
    }

    error_code, default_message = finish_reason_map.get(
        finish_reason,
        (LLMErrorCode.UNKNOWN_ERROR, f"未知的 finish_reason: {finish_reason}")
    )

    # 如果有 error_message，添加到消息中
    if error_message:
        default_message += f" | API Error: {error_message}"

    return create_llm_error(
        error_code=error_code,
        message=default_message,
        finish_reason=finish_reason,
        error_message=error_message,
        raw_response=json.dumps(response_data, ensure_ascii=False, indent=2)[:2000] if response_data else None,
        request_info=request_info,
    )


def handle_response_validation_error(
    validation_error: str,
    raw_response: Optional[str] = None,
    request_info: Optional[Dict[str, Any]] = None
) -> LLMError:
    """处理响应验证错误

    Args:
        validation_error: 验证错误信息
        raw_response: 原始响应
        request_info: 请求信息

    Returns:
        LLMError 实例
    """
    error_code = LLMErrorCode.MISSING_CHOICES
    if "JSON" in validation_error or "json" in validation_error:
        error_code = LLMErrorCode.JSON_DECODE_ERROR

    return create_llm_error(
        error_code=error_code,
        message=validation_error,
        raw_response=raw_response[:2000] if raw_response else None,
        request_info=request_info,
    )


def _parse_error_response(response_text: str) -> Optional[Dict[str, Any]]:
    """解析错误响应 JSON"""
    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        return None


class LLMErrorLogger:
    """LLM 错误日志记录器"""

    def __init__(self, logger_name: str = "app.services.llm_service"):
        self.logger = logging.getLogger(logger_name)

    def log_request_start(
        self,
        model: str,
        messages_count: int,
        temperature: float,
        max_tokens: int,
        stream: bool,
        enable_thinking: bool,
        has_tools: bool = False,
    ):
        """记录请求开始日志"""
        self.logger.info(
            "[LLM.REQUEST] 开始调用 | model=%s, messages=%d, temperature=%.2f, "
            "max_tokens=%d, stream=%s, thinking=%s, tools=%s",
            model, messages_count, temperature, max_tokens, stream, enable_thinking, has_tools
        )

    def log_request_success(
        self,
        model: str,
        duration_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        finish_reason: Optional[str] = None,
        has_reasoning: bool = False,
        has_tool_calls: bool = False,
    ):
        """记录请求成功日志"""
        self.logger.info(
            "[LLM.SUCCESS] 调用成功 | model=%s, duration=%.2fms, "
            "tokens=%d (prompt=%d, completion=%d), finish_reason=%s, "
            "has_reasoning=%s, has_tool_calls=%s",
            model, duration_ms, total_tokens, prompt_tokens, completion_tokens,
            finish_reason or "N/A", has_reasoning, has_tool_calls
        )

    def log_request_error(
        self,
        error: LLMError,
        model: str,
        duration_ms: float,
        extra_info: Optional[Dict[str, Any]] = None,
    ):
        """记录请求错误日志"""
        details = error.details

        log_data = {
            "error_code": details.error_code.value,
            "message": details.message,
            "model": model,
            "duration_ms": duration_ms,
            "http_status": details.http_status,
            "finish_reason": details.finish_reason.value if details.finish_reason else None,
            "retryable": details.retryable,
        }

        if extra_info:
            log_data.update(extra_info)

        # 根据错误严重程度选择日志级别
        if details.error_code in [
            LLMErrorCode.SERVER_ERROR,
            LLMErrorCode.SERVICE_UNAVAILABLE,
            LLMErrorCode.UNKNOWN_ERROR,
        ]:
            self.logger.error(
                "[LLM.ERROR] %s | details=%s",
                error,
                json.dumps(log_data, ensure_ascii=False, default=str)
            )
        elif details.error_code in [
            LLMErrorCode.RATE_LIMIT_ERROR,
            LLMErrorCode.TIMEOUT_ERROR,
        ]:
            self.logger.warning(
                "[LLM.WARNING] %s | details=%s",
                error,
                json.dumps(log_data, ensure_ascii=False, default=str)
            )
        else:
            self.logger.error(
                "[LLM.ERROR] %s | details=%s",
                error,
                json.dumps(log_data, ensure_ascii=False, default=str)
            )

        # 调试信息记录到 debug 级别
        if details.raw_response:
            self.logger.debug("[LLM.DEBUG] Raw response: %s", details.raw_response[:1000])

    def log_stream_chunk(
        self,
        model: str,
        chunk_index: int,
        has_content: bool = False,
        has_reasoning: bool = False,
        has_tool_calls: bool = False,
        finish_reason: Optional[str] = None,
    ):
        """记录流式 chunk 日志（仅调试级别）"""
        self.logger.debug(
            "[LLM.STREAM] chunk=%d, has_content=%s, has_reasoning=%s, "
            "has_tool_calls=%s, finish_reason=%s",
            chunk_index, has_content, has_reasoning, has_tool_calls, finish_reason or "N/A"
        )

    def log_stream_complete(
        self,
        model: str,
        duration_ms: float,
        total_chunks: int,
        total_tokens: int,
        finish_reason: Optional[str] = None,
    ):
        """记录流式调用完成日志"""
        self.logger.info(
            "[LLM.STREAM_COMPLETE] 流式调用完成 | model=%s, duration=%.2fms, "
            "chunks=%d, tokens=%d, finish_reason=%s",
            model, duration_ms, total_chunks, total_tokens, finish_reason or "N/A"
        )

    def log_token_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cached_tokens: Optional[int] = None,
        reasoning_tokens: Optional[int] = None,
    ):
        """记录详细的 token 使用日志"""
        self.logger.info(
            "[LLM.USAGE] Token 使用详情 | model=%s, prompt=%d, completion=%d, "
            "total=%d, cached=%s, reasoning=%s",
            model, prompt_tokens, completion_tokens, total_tokens,
            cached_tokens or "N/A", reasoning_tokens or "N/A"
        )

    def log_content_filter_triggered(
        self,
        model: str,
        filter_type: str,
        triggered_content: Optional[str] = None,
    ):
        """记录内容过滤触发日志"""
        self.logger.warning(
            "[LLM.CONTENT_FILTER] 内容过滤触发 | model=%s, filter_type=%s, "
            "content_preview=%s",
            model, filter_type,
            (triggered_content[:100] + "...") if triggered_content else "N/A"
        )

    def log_retry_attempt(
        self,
        model: str,
        attempt: int,
        max_retries: int,
        error_code: str,
        wait_seconds: float,
    ):
        """记录重试日志"""
        self.logger.warning(
            "[LLM.RETRY] 第 %d/%d 次重试 | model=%s, error=%s, wait=%.2fs",
            attempt, max_retries, model, error_code, wait_seconds
        )


# 全局错误日志记录器实例
llm_error_logger = LLMErrorLogger()
