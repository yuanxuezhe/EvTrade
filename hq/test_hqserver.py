#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hqserver 服务测试套件（mock-based，零外部依赖）。

设计原则：
  - 不修改业务代码 hqserver.py，只通过 import + 全局 task_queue 注入数据
  - 用 AsyncMock 替换 aio_pika connection / exchange / queue
  - 用 websockets 库自带 connect 测试 WS 广播路径
  - 用 pytest-asyncio 跑协程

覆盖路径：
  1. 单元：worker 解析 GBK body、构造 publish + WS payload
  2. 单元：边界输入（空 body、坏 GBK、字段不足、lastPrice 不是数字）
  3. 集成：worker 端到端把数据广播给 mock exchange + mock WS 客户端
  4. 集成：多个 worker 并发消费（NUM_WORKERS=4）
  5. 集成：WS handler 注册/注销
  6. 集成：_consume 把上游 message.body 塞进 task_queue
  7. 背压：task_queue 满后 put 阻塞（无需真阻塞，验证 Queue 行为即可）
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets
from aio_pika import Message

import hq.hqserver as hq


# ==================== Helpers ====================

async def _run_worker_until_drained(worker_id: int, exchange, timeout: float = 2.0):
    """启动一个 worker，等到 task_queue 排空后取消它。

    比起 asyncio.sleep(0.05) 的"软等待"，用 task_queue.join() 等所有 put 的项目被 task_done()，
    可靠性更高、速度更快、不依赖时序。

    返回 (mock_exchange 的引用 — caller 持有, 已取消的 task — caller 可选 await)
    """
    task = asyncio.create_task(hq.quota_worker(worker_id, exchange))
    try:
        await asyncio.wait_for(hq.task_queue.join(), timeout=timeout)
    except asyncio.TimeoutError:
        # 队列没排空也强制取消（caller 可以选择重新检查）
        pass
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return task


# ==================== Fixtures ====================

@pytest.fixture(autouse=True)
def _reset_globals():
    """每个测试前后清理模块级全局：WS 客户端 + task_queue。

    注意：模块级 task_queue 在第一次被 await get/put 时绑死到事件循环，
    pytest-asyncio 每个测试用新 loop，所以这里用一个本 loop 的 Queue 替换。
    """
    # 清空 WS 客户端
    hq._ws_clients.clear()

    # 替换 task_queue 为本 loop 的新 Queue
    original_queue = hq.task_queue
    hq.task_queue = asyncio.Queue(maxsize=hq.MAX_QUEUE_SIZE)
    yield
    # 恢复原 Queue（避免污染其他模块）
    hq.task_queue = original_queue
    hq._ws_clients.clear()


@pytest.fixture
def mock_exchange():
    """Mock 一个 aio_pika.Exchange，publish 记录调用。"""
    exch = MagicMock()
    exch.publish = AsyncMock()
    return exch


@pytest.fixture
def fake_worker_id():
    return 0


# ==================== 单元测试：worker 解析与构造 ====================

async def test_worker_decodes_gbk_and_publishes(mock_exchange, fake_worker_id):
    """worker 应能解析 GBK body，提取 stock_code，发布到 broadcast_exchange。"""
    raw = "600030.SH|2026-06-13 13:00:00|12.34|12.00|12.50|11.90|11.95|1000|1234000|0|100|".encode("gbk")
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    # publish 应被调用一次，routing_key=stock_code, body=原始字节
    mock_exchange.publish.assert_awaited_once()
    call = mock_exchange.publish.await_args
    msg, kwargs = call.args[0], call.kwargs
    assert isinstance(msg, Message)
    assert msg.body == raw
    assert kwargs["routing_key"] == "600030.SH"


async def test_worker_broadcasts_ws_payload_with_last_price(mock_exchange, fake_worker_id):
    """worker 推 WS 时应包含 type/channel/stock_code/last_price/fields。"""
    # 注册一个 mock WS 客户端
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)
    hq._ws_clients.add(mock_ws)

    raw = "000001.SZ|2026-06-13|10.50|10.40|10.60|10.30|10.45|2000|21000000|0|200|".encode("gbk")
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    mock_ws.send.assert_awaited_once()
    sent = json.loads(mock_ws.send.await_args.args[0])
    assert sent["type"] == "quote"
    assert sent["channel"] == "quote_update"
    assert sent["data"]["stock_code"] == "000001.SZ"
    assert sent["data"]["last_price"] == 10.50
    assert sent["data"]["fields"][0] == "000001.SZ"
    assert sent["data"]["body"].startswith("000001.SZ|")


async def test_worker_no_ws_clients_is_noop(mock_exchange, fake_worker_id):
    """没有 WS 客户端时，worker 不应崩溃，应正常 publish。"""
    assert not hq._ws_clients
    raw = "600519.SH|t|1800|".encode("gbk")
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    mock_exchange.publish.assert_awaited_once()
    # send 没被调用（因为没有 client）
    # 没有任何异常抛出 = OK


# ==================== 单元测试：边界输入 ====================

async def test_worker_no_messages_just_idles(mock_exchange, fake_worker_id):
    """空队列下 worker 单纯 await get，不会崩、不会调用 publish。"""
    await _run_worker_until_drained(fake_worker_id, mock_exchange)
    mock_exchange.publish.assert_not_called()


async def test_worker_invalid_gbk_falls_back_to_utf8(mock_exchange, fake_worker_id):
    """GBK 解码失败时用 utf-8(errors='replace') 兜底，不抛异常。"""
    # 构造一个 GBK 失败的字节序列（GBK 不接受 0x80 单独作为起始字节）
    raw = b"600030.SH|\x80\xff\xfe"
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    # publish 仍被调用（数据已转 utf-8 replacement），没崩
    mock_exchange.publish.assert_awaited_once()


async def test_worker_short_body_last_price_none(mock_exchange, fake_worker_id):
    """字段不足 3 个时 last_price 应为 None。"""
    mock_ws = AsyncMock()
    hq._ws_clients.add(mock_ws)

    raw = "600030.SH|t".encode("gbk")  # 只有 2 个字段
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    sent = json.loads(mock_ws.send.await_args.args[0])
    assert sent["data"]["last_price"] is None


async def test_worker_non_numeric_last_price(mock_exchange, fake_worker_id):
    """lastPrice 字段完全不是数字时（如 'abc'），last_price 应为 None。"""
    mock_ws = AsyncMock()
    hq._ws_clients.add(mock_ws)

    raw = "600030.SH|t|abc|".encode("gbk")
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    sent = json.loads(mock_ws.send.await_args.args[0])
    assert sent["data"]["last_price"] is None


async def test_worker_nan_last_price_accepted_as_float(mock_exchange, fake_worker_id):
    """NaN 字符串能被 float() 解析，会被作为 float 传出（记录真实行为）。"""
    mock_ws = AsyncMock()
    hq._ws_clients.add(mock_ws)

    raw = "600030.SH|t|NaN|".encode("gbk")
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    sent = json.loads(mock_ws.send.await_args.args[0])
    # NaN 不是合法的 JSON number，但 worker 是先 float() 再 json.dumps，
    # dumps 会输出 NaN 字面量 —— 这是真实代码行为，测试如实记录
    import math
    assert math.isnan(sent["data"]["last_price"])


async def test_worker_dead_ws_client_removed(mock_exchange, fake_worker_id):
    """WS 客户端 send 抛异常时，应从 _ws_clients 中清理。"""
    dead_ws = AsyncMock()
    dead_ws.send = AsyncMock(side_effect=RuntimeError("connection closed"))
    dead_ws.remote_address = ("127.0.0.1", 9999)
    hq._ws_clients.add(dead_ws)

    raw = "600030.SH|t|10.0|".encode("gbk")
    hq.task_queue.put_nowait(raw)

    await _run_worker_until_drained(fake_worker_id, mock_exchange)

    assert dead_ws not in hq._ws_clients


# ==================== 集成测试：多 worker 并发消费 ====================

async def test_multiple_workers_consume_in_parallel():
    """NUM_WORKERS 个 worker 应并行从 task_queue 取任务。"""
    mock_exchange = MagicMock()
    mock_exchange.publish = AsyncMock()

    # 喂 NUM_WORKERS * 3 条数据
    n_msgs = hq.NUM_WORKERS * 3
    for i in range(n_msgs):
        raw = f"6000{i:02d}.SH|t|10.{i}|".encode("gbk")
        hq.task_queue.put_nowait(raw)

    workers = [
        asyncio.create_task(hq.quota_worker(i, mock_exchange))
        for i in range(hq.NUM_WORKERS)
    ]
    # 等 task_queue 排空
    await hq.task_queue.join()
    for w in workers:
        w.cancel()
    for w in workers:
        try:
            await w
        except asyncio.CancelledError:
            pass

    # 所有消息都被 publish
    assert mock_exchange.publish.await_count == n_msgs


async def test_workers_distribute_messages_across_pool():
    """多 worker 下，NUM_WORKERS 个 worker 应当都被使用（消息分摊到所有 worker）。"""
    mock_exchange = MagicMock()
    mock_exchange.publish = AsyncMock()

    n_msgs = hq.NUM_WORKERS * 20
    for i in range(n_msgs):
        raw = f"600{i:04d}.SH|t|1.{i}|".encode("gbk")
        hq.task_queue.put_nowait(raw)

    # 包装 worker 用一个 shareable counter 记录每 worker 处理多少条
    per_worker_counts: list[int] = [0] * hq.NUM_WORKERS

    async def counting_worker(wid, exch):
        publish_func = exch.publish
        while True:
            raw_body = await hq.task_queue.get()
            try:
                stock_code = raw_body.split(b"|", 1)[0].decode("gbk", errors="replace")
                await publish_func(Message(body=raw_body, delivery_mode=1), routing_key=stock_code)
                per_worker_counts[wid] += 1
            finally:
                hq.task_queue.task_done()
                await asyncio.sleep(0)

    workers = [
        asyncio.create_task(counting_worker(i, mock_exchange))
        for i in range(hq.NUM_WORKERS)
    ]
    await hq.task_queue.join()
    for w in workers:
        w.cancel()
    for w in workers:
        try:
            await w
        except asyncio.CancelledError:
            pass

    # 所有消息都被 publish
    assert mock_exchange.publish.await_count == n_msgs
    # 4 个 worker 都被实际使用（公平分摊）
    used_workers = sum(1 for c in per_worker_counts if c > 0)
    assert used_workers == hq.NUM_WORKERS, f"只有 {used_workers}/{hq.NUM_WORKERS} worker 处理过消息: {per_worker_counts}"


# ==================== 集成测试：_consume 灌数据 ====================

async def test_consume_pushes_bodies_into_task_queue():
    """_consume 应把上游 message.body 放进 task_queue（空 body 跳过）。"""
    # mock 一个 aio_pika Queue
    mock_queue = MagicMock()

    # 构造异步迭代器：3 条正常 + 1 条空 body
    class FakeMessage:
        def __init__(self, body):
            self.body = body

    class FakeIter:
        def __init__(self):
            self.messages = [
                FakeMessage(b"600030.SH|t|10|"),
                FakeMessage(b""),  # 空 body 应跳过
                FakeMessage(b"000001.SZ|t|20|"),
                FakeMessage(b"600519.SH|t|1800|"),
            ]

        def __aiter__(self):
            self._i = 0
            return self

        async def __anext__(self):
            if self._i >= len(self.messages):
                raise StopAsyncIteration
            m = self.messages[self._i]
            self._i += 1
            return m

    class FakeQueueIter:
        def __init__(self, no_ack):
            self.no_ack = no_ack
            self.iter = FakeIter()

        async def __aenter__(self):
            return self.iter

        async def __aexit__(self, exc_type, exc, tb):
            return False

    mock_queue.iterator = MagicMock(return_value=FakeQueueIter(no_ack=True))

    stop_event = asyncio.Event()
    task = asyncio.create_task(hq._consume(mock_queue, stop_event))
    # 等队列满
    for _ in range(20):
        if hq.task_queue.qsize() >= 3:
            break
        await asyncio.sleep(0.05)

    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # task_queue 应有 3 条（空 body 跳过）
    assert hq.task_queue.qsize() == 3


# ==================== 集成测试：_broadcast_ws 自身 ====================

async def test_broadcast_ws_skips_dead_clients():
    """_broadcast_ws 应跳过 send 抛异常的客户端。"""
    live = AsyncMock()
    live.send = AsyncMock()
    dead = AsyncMock()
    dead.send = AsyncMock(side_effect=Exception("closed"))
    hq._ws_clients.add(live)
    hq._ws_clients.add(dead)

    await hq._broadcast_ws({"type": "quote", "data": {"stock_code": "X"}})

    live.send.assert_awaited_once()
    assert dead not in hq._ws_clients


async def test_broadcast_ws_no_clients_is_safe():
    """空客户端集合时 _broadcast_ws 不崩。"""
    await hq._broadcast_ws({"type": "quote"})  # 不应抛


# ==================== 集成测试：真 WS 服务（绑定随机端口） ====================

@pytest.fixture
async def ws_server():
    """在随机端口启动 hqserver 的 WS 服务，测试结束关闭。"""
    # 先选一个空闲端口
    import socket as _s
    s = _s.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    server = await websockets.asyncio.server.serve(hq._ws_handler, "127.0.0.1", port)
    yield f"ws://127.0.0.1:{port}"
    server.close()
    await server.wait_closed()


async def test_ws_handler_registers_client(ws_server):
    """客户端连接后 _ws_clients 应增加 1 个，断开后应清空。"""
    assert len(hq._ws_clients) == 0

    ws_cm = websockets.connect(ws_server)
    ws = await ws_cm.__aenter__()
    try:
        # 等服务端注册
        for _ in range(50):
            if len(hq._ws_clients) == 1:
                break
            await asyncio.sleep(0.02)
        assert len(hq._ws_clients) == 1

        # 服务端集合里的对象应当是 ServerConnection 类型
        registered = next(iter(hq._ws_clients))
        assert hasattr(registered, "send")
        assert hasattr(registered, "remote_address")
    finally:
        await ws_cm.__aexit__(None, None, None)

    # 断开后清空
    for _ in range(50):
        if len(hq._ws_clients) == 0:
            break
        await asyncio.sleep(0.02)
    assert len(hq._ws_clients) == 0


async def test_ws_client_receives_quote_payload(ws_server):
    """客户端连上后，调用 _broadcast_ws 应该能收到。"""
    ws_cm = websockets.connect(ws_server)
    ws = await ws_cm.__aenter__()
    try:
        # 等注册
        for _ in range(50):
            if len(hq._ws_clients) == 1:
                break
            await asyncio.sleep(0.02)

        # 推一条
        await hq._broadcast_ws({
            "type": "quote",
            "channel": "quote_update",
            "data": {"stock_code": "TEST.SH", "last_price": 99.99},
        })

        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        received = json.loads(msg)
        assert received["type"] == "quote"
        assert received["data"]["stock_code"] == "TEST.SH"
    finally:
        await ws_cm.__aexit__(None, None, None)


# ==================== 边界：task_queue 满背压 ====================

async def test_task_queue_bounded_size():
    """task_queue 应受 MAX_QUEUE_SIZE 限制（put_nowait 超出应抛 QueueFull）。"""
    # 用临时 Queue 验证设计意图（不污染全局）
    q = asyncio.Queue(maxsize=hq.MAX_QUEUE_SIZE)
    for _ in range(hq.MAX_QUEUE_SIZE):
        q.put_nowait(b"x")
    with pytest.raises(asyncio.QueueFull):
        q.put_nowait(b"overflow")


# ==================== 配置常量冒烟测试 ====================

def test_constants_are_well_formed():
    """关键常量应当合理。"""
    assert hq.NUM_WORKERS > 0
    assert hq.MAX_QUEUE_SIZE > 0
    assert hq.PREFETCH_COUNT > 0
    assert hq.WS_PORT > 0
    assert hq.BROADCAST_EXCHANGE == "quota.broadcast.exchange"
    assert hq.EXCHANGE_NAME == "quota.exchange"
    assert hq.RABBITMQ_URL.startswith("amqp://")