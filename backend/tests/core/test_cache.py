"""
ToolResultCache 测试
"""

import pytest
import time
from app.agent.core.cache import ToolResultCache


class TestToolResultCache:
    """ToolResultCache 测试"""

    @pytest.fixture
    def cache(self):
        return ToolResultCache(max_size=10, default_ttl=1)

    def test_set_and_get(self, cache):
        cache.set("tool1", {"param": "value"}, {"result": "ok"})
        result = cache.get("tool1", {"param": "value"})
        assert result == {"result": "ok"}

    def test_get_nonexistent(self, cache):
        result = cache.get("nonexistent", {})
        assert result is None

    def test_ttl_expiration(self, cache):
        cache.set("tool1", {"param": "value"}, {"result": "ok"}, ttl=0.1)
        time.sleep(0.2)
        result = cache.get("tool1", {"param": "value"})
        assert result is None

    def test_lru_eviction(self, cache):
        # 填满缓存
        for i in range(10):
            cache.set(f"tool{i}", {"param": i}, {"result": i})

        # 添加新条目，应该淘汰最旧的
        cache.set("tool_new", {"param": "new"}, {"result": "new"})

        # 最旧的应该被淘汰
        assert cache.get("tool0", {"param": 0}) is None
        # 新的应该存在
        assert cache.get("tool_new", {"param": "new"}) == {"result": "new"}

    def test_clear(self, cache):
        cache.set("tool1", {}, {"result": "ok"})
        count = cache.clear()
        assert count == 1
        assert cache.get("tool1", {}) is None

    def test_cleanup_expired(self, cache):
        cache.set("tool1", {}, {"result": "ok"}, ttl=0.1)
        cache.set("tool2", {}, {"result": "ok"}, ttl=10)
        time.sleep(0.2)

        count = cache.cleanup_expired()
        assert count == 1
        assert cache.get("tool1", {}) is None
        assert cache.get("tool2", {}) == {"result": "ok"}

    def test_has(self, cache):
        cache.set("tool1", {"param": "value"}, {"result": "ok"})
        assert cache.has("tool1", {"param": "value"}) is True
        assert cache.has("tool1", {"param": "other"}) is False
        assert cache.has("nonexistent", {}) is False

    def test_stats(self, cache):
        cache.set("tool1", {}, {"result": "ok"})
        cache.get("tool1", {})
        cache.get("nonexistent", {})

        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1
        assert stats["hit_rate"] == 0.5

    def test_get_all_keys(self, cache):
        cache.set("tool1", {"p": 1}, {"r": 1})
        cache.set("tool2", {"p": 2}, {"r": 2})
        keys = cache.get_all_keys()
        assert len(keys) == 2
