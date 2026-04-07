import asyncio
import time
from collections import deque
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    LLM 流控管理器
    限制 RPM (Requests Per Minute) 和 TPM (Tokens Per Minute)
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
                logger.warning(f"RPM 限制触发: 当前请求数 {len(self.request_timestamps)}, 需要等待 {wait_time:.2f} 秒")
                return wait_time

            # 检查 TPM 限制
            current_tpm = sum(token for _, token in self.token_usage)
            if current_tpm + estimated_tokens > self.tpm:
                # 计算需要等待的时间
                if self.token_usage:
                    oldest_token_time = self.token_usage[0][0]
                    wait_time = 60 - (current_time - oldest_token_time)
                    logger.warning(f"TPM 限制触发: 当前 token 数 {current_tpm}, 需要等待 {wait_time:.2f} 秒")
                    return wait_time
                else:
                    # 如果没有历史记录但仍然超过限制，说明单次请求过大
                    logger.warning(f"单次请求 token 数 {estimated_tokens} 超过 TPM 限制 {self.tpm}")
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

    async def wait_for_permission(self, estimated_tokens: int = 0):
        """
        等待流控许可，如果需要等待则阻塞

        Args:
            estimated_tokens: 预估的 token 数量
        """
        wait_time = await self.acquire(estimated_tokens)
        if wait_time > 0:
            logger.info(f"流控等待: {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)


# 全局流控实例
settings = get_settings()
rate_limiter = RateLimiter(rpm=settings.LLM_RPM, tpm=settings.LLM_TPM)
