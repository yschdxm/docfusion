import asyncio
import time
from collections import deque
import logging
from typing import Optional, Dict, Any
from app.core.llm_errors import (
    LLMErrorCode,
    create_llm_error,
    llm_error_logger,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    LLM 流控管理器
    限制 RPM (Requests Per Minute) 和 TPM (Tokens Per Minute)

    与错误处理机制集成：
    - 当 API 返回 429 时，提取 retry-after 时间
    - 记录流控相关日志
    - 提供流控统计信息
    """

    def __init__(self, rpm: int = 100, tpm: int = 10_000_000):
        """
        初始化流控管理器

        Args:
            rpm: 每分钟最大请求数
            tpm: 每分钟最大 token 数
        """
        self.rpm = rpm
        self.tpm = tpm

        # 请求队列 (存储时间戳)
        self.request_timestamps = deque()
        # Token 使用队列 (存储 (时间戳, token_count))
        self.token_usage = deque()

        # 用于同步的锁
        self._lock = asyncio.Lock()

        # 统计信息
        self._stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "rate_limit_hits": 0,  # 触发流控次数
            "total_wait_time": 0.0,  # 总等待时间
        }

    async def acquire(self, estimated_tokens: int = 0) -> float:
        """
        获取流控许可

        Args:
            estimated_tokens: 预估的 token 数量

        Returns:
            float: 需要等待的秒数 (0 表示无需等待)
        """
        async with self._lock:
            current_time = time.time()
            minute_ago = current_time - 60

            # 清理过期的请求记录
            while self.request_timestamps and self.request_timestamps[0] < minute_ago:
                self.request_timestamps.popleft()

            # 清理过期的 token 记录
            while self.token_usage and self.token_usage[0][0] < minute_ago:
                self.token_usage.popleft()

            # 检查 RPM 限制
            if len(self.request_timestamps) >= self.rpm:
                # 计算需要等待的时间
                oldest_request = self.request_timestamps[0]
                wait_time = 60 - (current_time - oldest_request)
                self._stats["rate_limit_hits"] += 1

                llm_error_logger.log_retry_attempt(
                    model="rate_limiter",
                    attempt=1,
                    max_retries=1,
                    error_code="RPM_LIMIT",
                    wait_seconds=max(0, wait_time),
                )

                logger.warning(
                    "[RATE_LIMIT] RPM 限制触发 | 当前请求数=%d, 限制=%d, 需等待=%.2f秒",
                    len(self.request_timestamps), self.rpm, wait_time
                )
                return max(0, wait_time)

            # 检查 TPM 限制
            current_tpm = sum(token for _, token in self.token_usage)
            if current_tpm + estimated_tokens > self.tpm:
                self._stats["rate_limit_hits"] += 1

                # 计算需要等待的时间
                if self.token_usage:
                    oldest_token_time = self.token_usage[0][0]
                    wait_time = 60 - (current_time - oldest_token_time)

                    llm_error_logger.log_retry_attempt(
                        model="rate_limiter",
                        attempt=1,
                        max_retries=1,
                        error_code="TPM_LIMIT",
                        wait_seconds=max(0, wait_time),
                    )

                    logger.warning(
                        "[RATE_LIMIT] TPM 限制触发 | 当前token数=%d, 预估=%d, 限制=%d, 需等待=%.2f秒",
                        current_tpm, estimated_tokens, self.tpm, wait_time
                    )
                    return max(0, wait_time)
                else:
                    # 如果没有历史记录但仍然超过限制，说明单次请求过大
                    logger.warning(
                        "[RATE_LIMIT] 单次请求token数(%d)超过TPM限制(%d)",
                        estimated_tokens, self.tpm
                    )
                    return 60  # 等待一分钟

            return 0.0

    async def record_request(self, estimated_tokens: int = 0):
        """
        记录请求和 token 使用

        Args:
            estimated_tokens: 实际使用的 token 数量
        """
        async with self._lock:
            current_time = time.time()
            self.request_timestamps.append(current_time)
            if estimated_tokens > 0:
                self.token_usage.append((current_time, estimated_tokens))

            # 更新统计
            self._stats["total_requests"] += 1
            self._stats["total_tokens"] += estimated_tokens

    async def wait_for_permission(self, estimated_tokens: int = 0):
        """
        等待流控许可，如果需要等待则阻塞

        Args:
            estimated_tokens: 预估的 token 数量
        """
        wait_time = await self.acquire(estimated_tokens)
        if wait_time > 0:
            self._stats["total_wait_time"] += wait_time
            logger.info("[RATE_LIMIT] 流控等待中 | 等待=%.2f秒, 预估tokens=%d", wait_time, estimated_tokens)
            await asyncio.sleep(wait_time)
            logger.info("[RATE_LIMIT] 流控等待完成，继续执行")

    async def handle_api_rate_limit(
        self,
        retry_after: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> float:
        """
        处理 API 返回的 429 速率限制错误

        当 MiMO API 返回 429 时调用此方法，获取建议的等待时间

        Args:
            retry_after: API 返回的 retry-after 头（秒）
            error_message: 错误消息

        Returns:
            float: 建议等待的秒数
        """
        self._stats["rate_limit_hits"] += 1

        # 如果 API 提供了 retry-after，使用它
        if retry_after is not None and retry_after > 0:
            wait_time = retry_after
            logger.warning(
                "[RATE_LIMIT] API 返回 429 | 使用服务器建议等待时间=%.2f秒, message=%s",
                wait_time, error_message or "N/A"
            )
        else:
            # 否则使用默认退避策略
            wait_time = await self.acquire()
            if wait_time <= 0:
                wait_time = 1.0  # 至少等待1秒

            logger.warning(
                "[RATE_LIMIT] API 返回 429 | 使用默认等待时间=%.2f秒, message=%s",
                wait_time, error_message or "N/A"
            )

        self._stats["total_wait_time"] += wait_time

        llm_error_logger.log_retry_attempt(
            model="rate_limiter",
            attempt=1,
            max_retries=3,
            error_code="API_RATE_LIMIT_429",
            wait_seconds=wait_time,
        )

        return wait_time

    def get_stats(self) -> Dict[str, Any]:
        """获取流控统计信息（同步方法）"""
        current_time = time.time()
        minute_ago = current_time - 60

        # 清理过期记录以获取准确统计
        recent_requests = [
            ts for ts in self.request_timestamps
            if ts >= minute_ago
        ]
        recent_tokens = sum(
            token for ts, token in self.token_usage
            if ts >= minute_ago
        )

        return {
            "rpm_limit": self.rpm,
            "tpm_limit": self.tpm,
            "current_rpm": len(recent_requests),
            "current_tpm": recent_tokens,
            "rpm_usage_percent": (len(recent_requests) / self.rpm * 100) if self.rpm > 0 else 0,
            "tpm_usage_percent": (recent_tokens / self.tpm * 100) if self.tpm > 0 else 0,
            "total_requests": self._stats["total_requests"],
            "total_tokens": self._stats["total_tokens"],
            "rate_limit_hits": self._stats["rate_limit_hits"],
            "total_wait_time": round(self._stats["total_wait_time"], 2),
        }

    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "rate_limit_hits": 0,
            "total_wait_time": 0.0,
        }

    def update_limits(self, rpm: Optional[int] = None, tpm: Optional[int] = None):
        """
        更新流控限制

        Args:
            rpm: 新的RPM限制
            tpm: 新的TPM限制
        """
        if rpm is not None and rpm > 0:
            self.rpm = rpm
        if tpm is not None and tpm > 0:
            self.tpm = tpm
        logger.info("[RATE_LIMIT] 流控限制已更新 | RPM=%d, TPM=%d", self.rpm, self.tpm)

    async def apply_db_config(self, db) -> None:
        """从数据库应用流控配置"""
        from app.services.config_service import config_service

        rpm = await config_service.get_int(db, "llm_rpm", self.rpm)
        tpm = await config_service.get_int(db, "llm_tpm", self.tpm)

        self.update_limits(rpm=rpm, tpm=tpm)
        logger.info("流控配置已从数据库应用: RPM=%d, TPM=%d", self.rpm, self.tpm)

    async def create_rate_limit_error(
        self,
        retry_after: Optional[float] = None,
        error_message: Optional[str] = None,
        request_info: Optional[Dict[str, Any]] = None
    ):
        """
        创建速率限制错误

        当需要抛出速率限制错误时调用此方法
        """
        stats = self.get_stats()

        message = f"请求过于频繁，触发速率限制 | 当前RPM: {stats['current_rpm']}/{self.rpm}, TPM: {stats['current_tpm']}/{self.tpm}"
        if error_message:
            message += f" | {error_message}"

        return create_llm_error(
            error_code=LLMErrorCode.RATE_LIMIT_ERROR,
            message=message,
            http_status=429,
            request_info={
                **(request_info or {}),
                "rate_limit_stats": stats,
                "retry_after": retry_after,
            },
        )


# 全局流控实例（默认值，启动后会被数据库配置覆盖）
rate_limiter = RateLimiter(rpm=100, tpm=10_000_000)
