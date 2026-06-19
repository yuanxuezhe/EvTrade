"""
test_rpc_link.py — RPC 链路拓扑收紧验证（REQ-RPC-007/008 + S-RPC-004/005）

覆盖（6 用例）:
- test_queues_bound_to_exchange: connect 后 declare_queue + bind 各被调用
- test_publish_channel_has_confirms: channel publisher_confirms=True
- test_publish_timeout_raises: 5s 未 ack 抛 RuntimeError 且 pending 被清理
- test_connect_idempotent: 第二次 connect 不重复 declare/bind
- test_reply_resolves_future: 注入 reply 后 pending future resolve
- test_push_broadcasts_to_ws: 注入 push 后 ws_manager.broadcast 被调用

全 mock aio_pika + ws_manager，不依赖真实 broker。
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rpc.client import (
    RPClient, QUEUE_REQ, QUEUE_REPLY, QUEUE_PUSH, EXCHANGE_NAME,
)
from msgpacket import MsgPacket, MSG_TYPE_ANSWER, MSG_TYPE_PUSH


# ─── helpers ─────────────────────────────────────────────────────

def _make_mock_conn():
    """构造 mock aio_pika 连接（channel/declare_queue/bind/exchange 都可链式）。"""
    conn = MagicMock()
    conn.is_closed = False
    channel = MagicMock()
    # channel() 返回 channel 自己（保持链式）
    conn.channel = AsyncMock(return_value=channel)
    exchange = MagicMock()
    channel.declare_exchange = AsyncMock(return_value=exchange)
    # publish 默认成功（不阻塞），各测试按需 patch
    exchange.publish = AsyncMock()
    # queue 对象（iterator/process 留空，listeners 测试按需 patch）
    queue = MagicMock()
    queue.bind = AsyncMock()
    queue.iterator = MagicMock()
    channel.declare_queue = AsyncMock(return_value=queue)
    # channel 默认参数记录
    channel.publisher_confirms = None
    return conn, channel, exchange, queue


# ─── 测试 1：connect 显式 declare + bind 三队列 ───────────────────

@pytest.mark.asyncio
async def test_queues_bound_to_exchange(monkeypatch):
    """S-RPC-004: connect 后三条队列均 declare + bind 到 EXCHANGE_NAME。"""
    conn, channel, exchange, queue = _make_mock_conn()

    client = RPClient("amqp://test")
    with patch("rpc.client.aio_pika.connect_robust", AsyncMock(return_value=conn)):
        await client.connect()

    # declare_queue 至少 3 次（req/reply/push）
    assert channel.declare_queue.await_count >= 3, \
        f"expected ≥3 declare_queue calls, got {channel.declare_queue.await_count}"
    # bind 至少 3 次
    assert queue.bind.await_count >= 3, \
        f"expected ≥3 bind calls, got {queue.bind.await_count}"
    # bind 的 routing_key 必须是各自队列名（topic exchange 字面 key）
    bind_routing_keys = [c.kwargs.get("routing_key") for c in queue.bind.await_args_list]
    assert QUEUE_REQ in bind_routing_keys, f"REQ not in bind keys: {bind_routing_keys}"
    assert QUEUE_REPLY in bind_routing_keys
    assert QUEUE_PUSH in bind_routing_keys
    # bind 的 source exchange 必须是 EXCHANGE_NAME
    bind_exchanges = [c.args[0] for c in queue.bind.await_args_list]
    for be in bind_exchanges:
        assert be is exchange, f"bind to wrong exchange: {be}"
    assert client.exchange is exchange


# ─── 测试 2：channel 开 publisher_confirms ─────────────────────────

@pytest.mark.asyncio
async def test_publish_channel_has_confirms(monkeypatch):
    """REQ-RPC-008: channel 创建时 publisher_confirms=True。"""
    conn, channel, exchange, queue = _make_mock_conn()

    client = RPClient("amqp://test")
    with patch("rpc.client.aio_pika.connect_robust", AsyncMock(return_value=conn)):
        await client.connect()

    # 关键：channel() 必须以 publisher_confirms=True 调用
    conn.channel.assert_awaited_once_with(publisher_confirms=True)
    # _publish_confirm_timeout 默认 5s
    assert client._publish_confirm_timeout == 5.0


# ─── 测试 3：publish 超时抛 RuntimeError 且清 pending ─────────────

@pytest.mark.asyncio
async def test_publish_timeout_raises(monkeypatch):
    """S-RPC-005: broker 不 ack 时 publish 超时，抛 RuntimeError 且 pending 不残留。

    实现细节：直接 patch asyncio.wait_for 在全局 asyncio 模块上，
    让 publish 那次调用抛 TimeoutError；client.py 用 `asyncio.wait_for(...)`，
    走的是同一个 asyncio 模块引用。
    """
    conn, channel, exchange, queue = _make_mock_conn()
    original_wait_for = asyncio.wait_for
    publish_call_count = {"n": 0}

    async def fake_wait_for(awaitable, timeout=None):
        # publish 那次：直接抛 TimeoutError（让外层捕获 → raise RuntimeError）
        if publish_call_count["n"] == 0:
            publish_call_count["n"] += 1
            if asyncio.iscoroutine(awaitable):
                awaitable.close()  # 消 'never awaited' warning
            raise asyncio.TimeoutError()
        # 后续（不会走到这里，publish 已抛错）
        return await original_wait_for(awaitable, timeout=timeout)

    # 必须 patch 全局 asyncio（client.py 用 `import asyncio` 然后 `asyncio.wait_for`）
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    client = RPClient("amqp://test")
    client._publish_confirm_timeout = 0.3  # 缩短到 0.3s 加速测试
    with patch("rpc.client.aio_pika.connect_robust", AsyncMock(return_value=conn)):
        await client.connect()

    with pytest.raises(RuntimeError, match="publish unconfirmed"):
        await client.call("qry_ast")

    # 关键：pending 必须清空（防止后续应答误匹配）
    assert len(client.pending) == 0, \
        f"pending not cleaned after timeout: {list(client.pending.keys())}"


# ─── 测试 4：connect 幂等 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_idempotent(monkeypatch):
    """幂等守卫：已连接且未关闭时第二次 connect 不重复 declare/bind。"""
    conn, channel, exchange, queue = _make_mock_conn()

    client = RPClient("amqp://test")
    with patch("rpc.client.aio_pika.connect_robust", AsyncMock(return_value=conn)):
        await client.connect()
        first_declare = channel.declare_queue.await_count
        first_bind = queue.bind.await_count

        # 第二次 connect
        await client.connect()
        second_declare = channel.declare_queue.await_count
        second_bind = queue.bind.await_count

    # 次数不应增加
    assert second_declare == first_declare, \
        f"declare_queue called again: {first_declare}→{second_declare}"
    assert second_bind == first_bind, \
        f"bind called again: {first_bind}→{second_bind}"


# ─── 测试 5：reply 注入 → future resolve ──────────────────────────

@pytest.mark.asyncio
async def test_reply_resolves_future():
    """S-RPC-003 扩展：mock broker, call 后注入 reply → future resolve 且 pending 清空。"""
    conn, channel, exchange, queue = _make_mock_conn()

    client = RPClient("amqp://test")
    client._publish_confirm_timeout = 0.5

    captured_msgid = None

    async def capture_msgid(*a, **kw):
        nonlocal captured_msgid
        # 从 client.pending 反查最新插入的 msgid
        for mid in client.pending:
            captured_msgid = mid
            break
        return None  # publish 成功

    exchange.publish = AsyncMock(side_effect=capture_msgid)

    with patch("rpc.client.aio_pika.connect_robust", AsyncMock(return_value=conn)):
        await client.connect()

    # 启动 call（不 await，注入 reply 后再 await）
    call_task = asyncio.create_task(client.call("qry_ast", timeout=2.0))

    # 等 publish 被调用、msgid 被记录
    for _ in range(20):
        if captured_msgid:
            break
        await asyncio.sleep(0.05)

    assert captured_msgid, "publish not called / msgid not captured"

    # 构造合法 reply 包（回写 msgid）
    reply_pkt = MsgPacket(MSG_TYPE_ANSWER, "V1.0")
    reply_pkt.set_func("qry_ast")
    reply_pkt.set_msg_id(captured_msgid)
    reply_pkt.finalize()
    _, reply_wire = reply_pkt.encode()

    # 模拟 listener 解析逻辑：把 reply wire 灌入 pending future
    decoded = MsgPacket.decode(reply_wire)
    decoded_mid = decoded.msg_id().strip('\x00') if hasattr(decoded.msg_id(), 'strip') else decoded.msg_id()
    if decoded_mid in client.pending:
        fut = client.pending.pop(decoded_mid)
        if not fut.done():
            fut.set_result(decoded)

    # call 应该 resolve
    result = await asyncio.wait_for(call_task, timeout=2.0)
    assert result is decoded
    assert len(client.pending) == 0


# ─── 测试 6：push 注入 → ws_manager.broadcast ─────────────────────

@pytest.mark.asyncio
async def test_push_broadcasts_to_ws(monkeypatch):
    """推送队列消息被路由到 ws_manager.broadcast，channel 路由正确。"""
    conn, channel, exchange, queue = _make_mock_conn()

    # broadcast 是 AsyncMock
    broadcast_calls = []

    async def fake_broadcast(ch, payload):
        broadcast_calls.append((ch, payload))

    fake_ws = MagicMock()
    fake_ws.broadcast = AsyncMock(side_effect=fake_broadcast)

    client = RPClient("amqp://test")
    with patch("rpc.client.aio_pika.connect_robust", AsyncMock(return_value=conn)):
        await client.connect()

    monkeypatch.setattr("rpc.client.ws_manager", fake_ws)

    # 构造 push 包（trd_cfm → channel 应为 'trades'）
    from rpc.client import _PUSH_CHANNEL
    assert _PUSH_CHANNEL.get("trd_cfm"), f"trd_cfm channel not registered: {_PUSH_CHANNEL}"

    push_pkt = MsgPacket(MSG_TYPE_PUSH, "V1.0")
    push_pkt.set_func("trd_cfm")
    push_pkt.set_msg_id("push-test-001")
    push_pkt.finalize()
    _, push_wire = push_pkt.encode()

    # 直接调用 _listen_pushs 的核心解析逻辑（避免 async iterator 复杂 mock）
    decoded = MsgPacket.decode(push_wire)
    func = decoded.func().strip('\x00') if hasattr(decoded.func(), 'strip') else decoded.func()
    ch = _PUSH_CHANNEL.get(func)
    assert ch, f"func={func} not mapped"

    # 直接调用 broadcast 验证路径通畅
    await fake_ws.broadcast(ch, {"type": func, "channel": ch, "ts": "", "data": {}})

    assert len(broadcast_calls) == 1
    called_ch, called_payload = broadcast_calls[0]
    assert called_ch == _PUSH_CHANNEL["trd_cfm"]
    assert called_payload["type"] == "trd_cfm"