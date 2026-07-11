"""
HookSystem 测试
"""

import pytest
from app.agent.core.hook_system import (
    HookSystem,
    HookDefinition,
    HookEvent,
    HookContext,
    HookResult
)
from app.agent.base.tool import ToolResult


class TestHookSystem:
    """HookSystem 测试"""

    @pytest.fixture
    def hook_system(self):
        return HookSystem()

    def test_register(self, hook_system):
        hook = HookDefinition(
            name="test_hook",
            event=HookEvent.BEFORE_TOOL,
            handler=lambda ctx: HookResult()
        )
        hook_system.register(hook)
        assert "test_hook" in hook_system.get_hook_names()

    def test_unregister(self, hook_system):
        hook = HookDefinition(
            name="test_hook",
            event=HookEvent.BEFORE_TOOL,
            handler=lambda ctx: HookResult()
        )
        hook_system.register(hook)
        result = hook_system.unregister("test_hook")
        assert result is True
        assert "test_hook" not in hook_system.get_hook_names()

    def test_unregister_nonexistent(self, hook_system):
        result = hook_system.unregister("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_before_tool_hook(self, hook_system):
        called = False

        async def handler(ctx: HookContext):
            nonlocal called
            called = True
            return HookResult()

        hook = HookDefinition(
            name="test_hook",
            event=HookEvent.BEFORE_TOOL,
            handler=handler
        )
        hook_system.register(hook)

        result = await hook_system.before_tool("test_tool", {"param": "value"})
        assert called is True
        assert result.should_continue is True

    @pytest.mark.asyncio
    async def test_hook_modifies_params(self, hook_system):
        async def handler(ctx: HookContext):
            return HookResult(modified_params={"param": "modified"})

        hook = HookDefinition(
            name="modifier",
            event=HookEvent.BEFORE_TOOL,
            handler=handler
        )
        hook_system.register(hook)

        result = await hook_system.before_tool("test_tool", {"param": "original"})
        assert result.modified_params == {"param": "modified"}

    @pytest.mark.asyncio
    async def test_hook_stops_execution(self, hook_system):
        async def handler(ctx: HookContext):
            return HookResult(should_continue=False, error="Blocked")

        hook = HookDefinition(
            name="blocker",
            event=HookEvent.BEFORE_TOOL,
            handler=handler
        )
        hook_system.register(hook)

        result = await hook_system.before_tool("test_tool", {})
        assert result.should_continue is False

    @pytest.mark.asyncio
    async def test_after_tool_hook(self, hook_system):
        called = False

        async def handler(ctx: HookContext):
            nonlocal called
            called = True
            return HookResult()

        hook = HookDefinition(
            name="after_hook",
            event=HookEvent.AFTER_TOOL,
            handler=handler
        )
        hook_system.register(hook)

        result = await hook_system.after_tool("test_tool", {}, ToolResult(success=True))
        assert called is True

    @pytest.mark.asyncio
    async def test_on_error_hook(self, hook_system):
        called = False

        async def handler(ctx: HookContext):
            nonlocal called
            called = True
            return HookResult()

        hook = HookDefinition(
            name="error_hook",
            event=HookEvent.ON_ERROR,
            handler=handler
        )
        hook_system.register(hook)

        result = await hook_system.on_error("test_tool", {}, Exception("test error"))
        assert called is True

    def test_enable_disable(self, hook_system):
        hook_system.disable()
        assert hook_system.is_enabled() is False
        hook_system.enable()
        assert hook_system.is_enabled() is True

    def test_get_hooks(self, hook_system):
        hook1 = HookDefinition(
            name="hook1",
            event=HookEvent.BEFORE_TOOL,
            handler=lambda ctx: HookResult()
        )
        hook2 = HookDefinition(
            name="hook2",
            event=HookEvent.AFTER_TOOL,
            handler=lambda ctx: HookResult()
        )
        hook_system.register(hook1)
        hook_system.register(hook2)

        all_hooks = hook_system.get_hooks()
        assert len(all_hooks) == 2

        before_hooks = hook_system.get_hooks(HookEvent.BEFORE_TOOL)
        assert len(before_hooks) == 1
        assert before_hooks[0].name == "hook1"

    def test_tool_pattern_matching(self, hook_system):
        hook = HookDefinition(
            name="query_hook",
            event=HookEvent.BEFORE_TOOL,
            handler=lambda ctx: HookResult(),
            tool_pattern="query_*"
        )
        hook_system.register(hook)

        # 应该匹配 query_pg_database
        assert hook_system._should_run_for_tool(hook, "query_pg_database") is True
        # 不应该匹配 fill_table
        assert hook_system._should_run_for_tool(hook, "fill_table") is False

    def test_priority_ordering(self, hook_system):
        hook1 = HookDefinition(
            name="low_priority",
            event=HookEvent.BEFORE_TOOL,
            handler=lambda ctx: HookResult(),
            priority=10
        )
        hook2 = HookDefinition(
            name="high_priority",
            event=HookEvent.BEFORE_TOOL,
            handler=lambda ctx: HookResult(),
            priority=0
        )
        hook_system.register(hook1)
        hook_system.register(hook2)

        hooks = hook_system.get_hooks(HookEvent.BEFORE_TOOL)
        assert hooks[0].name == "high_priority"
        assert hooks[1].name == "low_priority"
