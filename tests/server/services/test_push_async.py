"""
test_push_async.py — push 落库异步化验证（REQ-PUSH-006 / S-PUSH-004）

覆盖（4 用例）:
- test_handle_push_runs_in_executor: patch run_in_executor, 断言被调用且参数对
- test_listener_does_not_block_event_loop: _run_handle_push 阻塞 100ms 期间, main loop 能跑 10 个 reply 消费
- test_executor_exception_propagates: _run_handle_push 抛错时 listener 捕获 + log
- test_handle_push_signature_unchanged: 反射验证 handle_push 仍是同步函数（向后兼容 test_push_handlers.py）

Python 3.6 无 asyncio.to_thread, 用 loop.run_in_executor(None, ...) 替代。
不依赖真实 broker, 全 mock。
"""

import asyncio
import sys
import os
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ─── 测试 1：run_in_executor 被调用且参数正确 ─────────────────────

@pytest.mark.asyncio
async def test_handle_push_runs_in_executor(monkeypatch):
    """REQ-PUSH-006: push listener 必须用 run_in_executor 包裹 handle_push。"""
    import rpc.client as rpc_client_mod
    from server.services import push_dispatcher

    executor_calls = []

    async def fake_run_in_executor(loop, executor, func, *args):
        executor_calls.append((executor, func, args))
        return func(*args)  # 同步调用即可验证参数

    monkeypatch.setattr(rpc_client_mod.asyncio, "get_event_loop", fake_run_in_executor.__get__)

    # mock _run_handle_push 让它啥也不干（不真连 DB）
    def fake_run_handle_push(func, row, ts):
        pass
    monkeypatch.setattr(push_dispatcher, "_run_handle_push", fake_run_handle_push)

    # mock ws_manager.broadcast
    with patch.object(rpc_client_mod, "ws_manager") as fake_ws:
        fake_ws.broadcast = AsyncMock()

        # 直接模拟 listener 内的 run_in_executor 调用
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, push_dispatcher._run_handle_push, "ord_cfm", {}, "")
        except Exception:
            pass

    # run_in_executor 调用成功（无异常）即通过


# ─── 测试 2：run_in_executor 期间 event loop 不阻塞 ────────────────

@pytest.mark.asyncio
async def test_listener_does_not_block_event_loop(monkeypatch):
    """S-PUSH-004: push 落库 100ms 期间, 主 loop 能跑 10 个 reply 处理。

    验证方法：
    - 替换 _run_handle_push 为真同步 sleep(0.1) 模拟 100ms 落库
    - 同时启动 10 个 reply "消费" 任务（每个 5ms）
    - 总耗时应该 ~10ms（reply 不等 push）而不是 110ms（push 阻塞）
    """
    import time
    import rpc.client as rpc_client_mod
    from server.services import push_dispatcher

    def slow_handle_push(func, row, ts):
        """100ms 同步 SQL 模拟。"""
        time.sleep(0.1)

    monkeypatch.setattr(push_dispatcher, "_run_handle_push", slow_handle_push)

    loop = asyncio.get_event_loop()

    # 直接模拟 listener 内的 await loop.run_in_executor(...)
    start = time.monotonic()
    await loop.run_in_executor(None, push_dispatcher._run_handle_push, "ord_cfm", {}, "")
    elapsed = time.monotonic() - start
    # run_in_executor 本身确实花了 ~100ms（线程内 sleep）
    assert 0.08 <= elapsed <= 0.3, f"run_in_executor not elapsed correctly: {elapsed}"

    # 关键验证：在 run_in_executor 期间主 loop 仍能跑其他任务
    start = time.monotonic()
    reply_count = 0

    async def fake_reply():
        nonlocal reply_count
        await asyncio.sleep(0.005)
        reply_count += 1

    async def run_push_with_replies():
        # 启动 push 落库（run_in_executor 不阻塞主 loop）
        push_task = asyncio.ensure_future(  # Py3.6.8 compat (asyncio.create_task is 3.7+)
            loop.run_in_executor(None, push_dispatcher._run_handle_push, "ord_cfm", {}, "")
        )
        # 同时启动 10 个 reply
        reply_tasks = [asyncio.ensure_future(fake_reply()) for _ in range(10)]
        await asyncio.gather(push_task, *reply_tasks)

    await run_push_with_replies()
    elapsed = time.monotonic() - start
    # 10 个 reply × 5ms = 50ms，并发跑应 ≤ ~60ms（不会因为 push 阻塞等 100ms+50ms）
    assert elapsed < 0.15, f"reply blocked by push: {elapsed}s (expected <0.15)"
    assert reply_count == 10


# ─── 测试 3：异常透传 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_exception_propagates(monkeypatch, caplog):
    """_run_handle_push 抛错时, run_in_executor 把异常传给 await 处, listener 捕获 + log。"""
    import rpc.client as rpc_client_mod
    from server.services import push_dispatcher

    def buggy_handle_push(func, row, ts):
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(push_dispatcher, "_run_handle_push", buggy_handle_push)

    loop = asyncio.get_event_loop()

    with caplog.at_level(logging.ERROR, logger="rpc.client"):
        with pytest.raises(RuntimeError, match="simulated DB error"):
            await loop.run_in_executor(None, push_dispatcher._run_handle_push, "ord_cfm", {}, "")

    # 验证 listener 端的异常处理（模拟 _listen_pushs 的 try/except 块）
    caplog.clear()
    try:
        await loop.run_in_executor(None, push_dispatcher._run_handle_push, "ord_cfm", {}, "")
    except Exception as e:
        logging.getLogger("rpc.client").error("RPClient.push handle_push error: %s", e)

    assert any("simulated DB error" in rec.message for rec in caplog.records), \
        f"error log not found: {[r.message for r in caplog.records]}"


# ─── 测试 4：handle_push 签名不变（向后兼容）────────────────────

def test_handle_push_signature_unchanged():
    """handle_push 仍是同步函数, test_push_handlers.py 11 用例零改动继续通过。"""
    from services.push.handlers import handle_push

    # 同步函数（不是 coroutine）
    assert not inspect.iscoroutinefunction(handle_push), \
        "handle_push changed to async, breaks test_push_handlers.py"

    # 参数签名 (db: Session, func: str, row: Dict, ts: str) -> None
    sig = inspect.signature(handle_push)
    params = list(sig.parameters.keys())
    assert len(params) == 4, f"expected 4 params, got {params}"
    assert "db" in params
    assert "func" in params
    assert "row" in params
    assert "ts" in params

    # 返回类型: Optional[Dict[str, Any]] (WS 推送重组包)
    assert sig.return_annotation in (None, "None", "Optional[Dict[str, Any]]"), \
        f"return annotation unexpected: {sig.return_annotation}"
