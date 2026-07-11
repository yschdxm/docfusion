"""
工具结果缓存 - 支持TTL过期和LRU淘汰

功能：
- 缓存工具执行结果
- TTL过期机制
- LRU淘汰策略
- 缓存统计
"""

import time
from typing import Any, Optional, Dict
from collections import OrderedDict
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class ToolResultCache:
    """工具结果缓存

    支持TTL过期和LRU淘汰策略。
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """
        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认TTL（秒）
        """
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._hit_count = 0
        self._miss_count = 0

    def _generate_key(self, tool_name: str, params: Dict[str, Any]) -> str:
        """生成缓存键

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            缓存键（MD5哈希）
        """
        # 将参数转换为稳定的JSON字符串
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        # 使用MD5哈希作为键
        key_content = f"{tool_name}:{params_str}"
        return hashlib.md5(key_content.encode()).hexdigest()

    def get(self, tool_name: str, params: Dict[str, Any]) -> Optional[Any]:
        """获取缓存结果

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            缓存的结果，如果不存在或已过期则返回None
        """
        key = self._generate_key(tool_name, params)

        if key not in self._cache:
            self._miss_count += 1
            return None

        entry = self._cache[key]

        # 检查是否过期
        if time.time() > entry["expires_at"]:
            del self._cache[key]
            self._miss_count += 1
            return None

        # LRU：移到末尾
        self._cache.move_to_end(key)
        self._hit_count += 1

        logger.debug(f"缓存命中: {tool_name}")
        return entry["value"]

    def set(
        self,
        tool_name: str,
        params: Dict[str, Any],
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """设置缓存

        Args:
            tool_name: 工具名称
            params: 工具参数
            value: 缓存的值
            ttl: TTL（秒），如果为None则使用默认TTL
        """
        key = self._generate_key(tool_name, params)

        # 如果缓存已满，淘汰最旧的条目
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
            logger.debug("缓存已满，淘汰最旧条目")

        self._cache[key] = {
            "value": value,
            "expires_at": time.time() + (ttl or self._default_ttl),
            "tool_name": tool_name,
            "created_at": time.time()
        }

        logger.debug(f"缓存设置: {tool_name}")

    def delete(self, tool_name: str, params: Dict[str, Any]) -> bool:
        """删除缓存

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            是否成功删除
        """
        key = self._generate_key(tool_name, params)
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"缓存删除: {tool_name}")
            return True
        return False

    def clear(self) -> int:
        """清空缓存

        Returns:
            清除的条目数
        """
        count = len(self._cache)
        self._cache.clear()
        self._hit_count = 0
        self._miss_count = 0
        logger.info(f"缓存已清空: {count} 条目")
        return count

    def cleanup_expired(self) -> int:
        """清理过期条目

        Returns:
            清理的条目数
        """
        now = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if now > entry["expires_at"]
        ]
        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.info(f"清理过期缓存: {len(expired_keys)} 条目")

        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计

        Returns:
            统计信息字典
        """
        now = time.time()
        total_requests = self._hit_count + self._miss_count
        hit_rate = self._hit_count / max(total_requests, 1)

        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "expired": sum(1 for e in self._cache.values() if now > e["expires_at"]),
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": hit_rate
        }

    def get_all_keys(self) -> list:
        """获取所有缓存键

        Returns:
            缓存键列表
        """
        return list(self._cache.keys())

    def has(self, tool_name: str, params: Dict[str, Any]) -> bool:
        """检查缓存是否存在且未过期

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            是否存在有效缓存
        """
        key = self._generate_key(tool_name, params)

        if key not in self._cache:
            return False

        entry = self._cache[key]

        # 检查是否过期
        if time.time() > entry["expires_at"]:
            del self._cache[key]
            return False

        return True


# 全局缓存实例
tool_result_cache = ToolResultCache()
