"""
server/tests/services/agent/test_agent_confirm.py — ConfirmRegistry 单测

REQ-ARCH-008 §二次确认协议：pending_confirmations 状态机
"""
import asyncio
import os
import time

import pytest

os.environ.setdefault("JWT_SECRET", "test_secret_for_unit_test_only_32bytes!!")

from server.services.agent.agent_confirm import ConfirmRegistry, ConfirmTimeoutError, get_confirm_registry  # noqa: E402


# ─── 1. register + await_confirmation + respond ─────────────────
class TestRegisterAndRespond:
    @pytest.mark.asyncio
    async def test_register_await_confirm_true(self):
        reg = ConfirmRegistry()
        key = await reg.register(
            run_id="r-1", tool_call_id="tc-1",
            tool_name="place_order", tool_params={"x": 1}, timeout=5.0,
        )
        # 用户确认
        asyncio.create_task(_delayed_respond(reg, key, confirmed=True, delay=0.1))
        result = await reg.await_confirmation(key)
        assert result is True

    @pytest.mark.asyncio
    async def test_register_await_confirm_false(self):
        reg = ConfirmRegistry()
        key = await reg.register(
            run_id="r-1", tool_call_id="tc-1",
            tool_name="place_order", tool_params={}, timeout=5.0,
        )
        asyncio.create_task(_delayed_respond(reg, key, confirmed=False, delay=0.1))
        result = await reg.await_confirmation(key)
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_raises_ConfirmTimeoutError(self):
        reg = ConfirmRegistry()
        key = await reg.register(
            run_id="r-1", tool_call_id="tc-1",
            tool_name="place_order", tool_params={}, timeout=0.3,
        )
        with pytest.raises(ConfirmTimeoutError):
            await reg.await_confirmation(key)


# ─── 2. respond idempotent / no-op on missing ───────────────────
class TestRespondIdempotent:
    @pytest.mark.asyncio
    async def test_respond_no_op_when_missing(self):
        reg = ConfirmRegistry()
        result = await reg.respond("nonexistent:key", confirmed=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_double_register_replaces_old(self):
        reg = ConfirmRegistry()
        key1 = await reg.register(
            run_id="r-1", tool_call_id="tc-1",
            tool_name="place_order", tool_params={"v": 1}, timeout=0.2,
        )
        # 第一次注册开始等待（不 respond，让它自然超时）
        with pytest.raises(ConfirmTimeoutError):
            await reg.await_confirmation(key1)

        # 第二次注册应 cancel/cleanup 旧 pending
        key2 = await reg.register(
            run_id="r-1", tool_call_id="tc-1",  # 同一 key
            tool_name="place_order", tool_params={"v": 2}, timeout=5.0,
        )
        assert key1 == key2  # 同一 pending_key
        assert await reg.pending_count() == 1

        # 用户确认 → 状态机解析
        await reg.respond(key2, confirmed=True)
        assert await reg.pending_count() == 0


# ─── 3. cleanup_expired ─────────────────────────────────────────
class TestCleanupExpired:
    @pytest.mark.asyncio
    async def test_expired_pending_gets_removed(self):
        reg = ConfirmRegistry()
        key = await reg.register(
            run_id="r-1", tool_call_id="tc-1",
            tool_name="place_order", tool_params={}, timeout=0.1,
        )
        assert await reg.pending_count() == 1
        # 等超时间 + 5s 扫描周期
        await asyncio.sleep(0.2)
        # 手动触发一次清理（不等 cleanup_loop）
        await reg._cleanup_expired()  # noqa: SLF001
        assert await reg.pending_count() == 0


# ─── 4. get_confirm_registry 单例 ──────────────────────────────
class TestSingleton:
    def test_get_returns_same_instance(self):
        r1 = get_confirm_registry()
        r2 = get_confirm_registry()
        assert r1 is r2


# ─── helper ──────────────────────────────────────────────────────
async def _delayed_respond(reg: ConfirmRegistry, key: str, confirmed: bool, delay: float):
    await asyncio.sleep(delay)
    await reg.respond(key, confirmed=confirmed)
