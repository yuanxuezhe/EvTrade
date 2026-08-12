"""
test_session.py — REQ-AUTH-IDLE-001 token session cache 单元测试

v128.2 (2026-08-12): cache 落 MySQL (ENGINE=MEMORY)
  - 原测试直接清模块级 dict (_TOKEN_CACHE.clear) → 现改为清表 (session._clear_all_for_test)
  - time.time() monkeypatch 仍生效: 内部所有"now"均派生自 time.time()
  - 需在测试 setup 跑一次 migration 建表 (autouse session fixture)

覆盖场景:
- register_token 后 is_valid 立即返 True
- revoke 后 is_valid 返 False
- touch 不影响 is_valid (只是更新 last_seen_at)
- 模拟 idle 超时: monkeypatch time.time → is_valid 返 False
- sweep_expired 清理过期条目
- sweep_loop 协程可被 CancelledError 优雅退出
"""
import asyncio
import importlib

import pytest

from server.auth import session


@pytest.fixture(scope="session", autouse=True)
def _ensure_token_sessions_table():
    """绕过 FastAPI startup, 直接调 migration 跑建表 (幂等)."""
    from server.infra.db import engine
    mod = importlib.import_module("server.migrations.2026-08-12-add-token-sessions")
    mod.migrate(engine)


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个 case 前清空 token_sessions 表, 避免 test 间污染."""
    session._clear_all_for_test()
    yield
    session._clear_all_for_test()


def test_register_then_is_valid():
    """注册后立即有效。"""
    session.register_token("t1", user_id=10, role="admin")
    assert session.is_valid("t1") is True
    assert session.is_valid("nonexistent") is False


def test_revoke_makes_invalid():
    """revoke 后 is_valid 立即返 False。"""
    session.register_token("t2", user_id=20, role="trader")
    assert session.is_valid("t2") is True
    session.revoke("t2")
    assert session.is_valid("t2") is False


def test_revoke_nonexistent_is_noop():
    """revoke 不存在的 token 不抛错。"""
    session.revoke("never-existed")  # 不抛错
    assert session.is_valid("never-existed") is False


def test_touch_keeps_valid():
    """touch 不改变 is_valid (只是更新 last_seen_at)。"""
    session.register_token("t3", user_id=30, role="viewer")
    assert session.is_valid("t3") is True
    session.touch("t3")
    assert session.is_valid("t3") is True


def test_touch_nonexistent_is_noop():
    """touch 不存在的 token 不抛错, 也无副作用。"""
    session.touch("ghost")
    assert session.stats()["size"] == 0


def test_idle_expires_after_timeout(monkeypatch):
    """模拟 idle 超时: 注入 time.time 返回值, 让 last_seen_at 看起来"过期"。"""
    fake_now = [1000.0]
    monkeypatch.setattr(session.time, "time", lambda: fake_now[0])

    session.register_token("t4", user_id=40, role="admin")
    # 注册时 fake_now = 1000.0, last_seen_at = 1000.0
    assert session.is_valid("t4") is True

    # 跳到 1000 + 599s: 仍有效 (未到 600s)
    fake_now[0] = 1000 + 599
    assert session.is_valid("t4") is True

    # 跳到 1000 + 601s: 已过期
    fake_now[0] = 1000 + 601
    assert session.is_valid("t4") is False


def test_touch_resets_idle_window(monkeypatch):
    """touch 后 last_seen_at 重置, 过期窗口重新计时。"""
    fake_now = [2000.0]
    monkeypatch.setattr(session.time, "time", lambda: fake_now[0])

    session.register_token("t5", user_id=50, role="trader")
    # 跳到 2000 + 599s: 仍有效
    fake_now[0] = 2000 + 599
    assert session.is_valid("t5") is True
    # touch 重置
    session.touch("t5")
    # 现在 last_seen_at = 2000+599, 再跳 599s 仍有效 (2000+599+599 < 2000+599+600)
    fake_now[0] = 2000 + 599 + 599
    assert session.is_valid("t5") is True
    # 再跳 2s: 超过 600s, 失效
    fake_now[0] = 2000 + 599 + 599 + 2
    assert session.is_valid("t5") is False


def test_sweep_expired_removes_only_expired(monkeypatch):
    """sweep_expired 只清过期的, 保留仍有效的。"""
    fake_now = [3000.0]
    monkeypatch.setattr(session.time, "time", lambda: fake_now[0])

    session.register_token("old1", user_id=1, role="admin")
    session.register_token("old2", user_id=2, role="admin")
    session.register_token("fresh", user_id=3, role="admin")

    # old1/old2 跳到 601s 后过期, fresh 跳到 100s (还在窗口)
    fake_now[0] = 3000 + 601
    session.touch("fresh")  # 重置 fresh

    removed = session.sweep_expired()
    assert removed == 2
    assert session.is_valid("old1") is False
    assert session.is_valid("old2") is False
    assert session.is_valid("fresh") is True


def test_sweep_expired_returns_zero_when_nothing_expired():
    """sweep_expired 全 fresh 时返 0。"""
    session.register_token("a", user_id=1, role="admin")
    session.register_token("b", user_id=2, role="admin")
    assert session.sweep_expired() == 0
    assert session.stats()["size"] == 2


def test_stats_reflects_cache_size():
    """stats() 反映当前 cache 大小。"""
    assert session.stats() == {"size": 0, "idle_timeout_seconds": session.IDLE_TIMEOUT_SECONDS}
    session.register_token("x", 1, "admin")
    session.register_token("y", 2, "trader")
    assert session.stats()["size"] == 2


def test_idle_timeout_constant_is_600():
    """REQ-AUTH-IDLE-001: 10 分钟 = 600 秒。"""
    assert session.IDLE_TIMEOUT_SECONDS == 600


def test_sweep_loop_exits_on_cancel(monkeypatch):
    """sweep_loop 协程能被 CancelledError 优雅退出。

    不依赖 pytest-asyncio: 用 asyncio.run + 在 task 外 cancel + 协程内部捕获后 raise。
    用 asyncio.sleep 真实短 sleep 让 task 跑起来 (0.05s 内足够进入下一次 sleep)。
    """
    import asyncio as real_asyncio

    async def _runner():
        task = real_asyncio.ensure_future(session.sweep_loop(interval_seconds=60))
        await real_asyncio.sleep(0.05)  # 让 sweep 进入 sleep
        task.cancel()
        with pytest.raises(real_asyncio.CancelledError):
            await task

    real_asyncio.run(_runner())


def test_token_hash_is_sha256():
    """v128.2: PK = SHA256(token) hex (64 字符), 不存原文."""
    h = session._hash_token("abc")
    assert len(h) == 64
    assert session._hash_token("abc") == h  # 确定性
    assert session._hash_token("abd") != h


def test_cross_session_isolation_via_token():
    """v128.2 regression: 不同 token 视为不同 session (与原 dict 语义一致)."""
    session.register_token("alpha", user_id=1, role="admin")
    session.register_token("beta", user_id=2, role="trader")
    assert session.is_valid("alpha") is True
    assert session.is_valid("beta") is True
    session.revoke("alpha")
    assert session.is_valid("alpha") is False
    assert session.is_valid("beta") is True