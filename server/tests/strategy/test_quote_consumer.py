"""
test_quote_consumer.py — QuoteConsumer 后端 WS 客户端单测（task 7）

覆盖：
- _parse_tick: 正确解析 hqserver JSON 格式（type=quote + channel=quote_update）
- _parse_tick: 非 quote_update 频道 / 缺字段 / 非法 JSON 静默返 None
- _fanout_tick: tick 路由到匹配 stock_code 的 engine
- _fanout_tick: 未订阅 stock_code 静默丢弃
- _load_engines + _load_prev_close: DB 读 active strategies + QuoteSnapshot 注入
- _connect: 指数退避（1 → 2 → 4 → 8 → 16 → 30 cap）

📌 设计取舍：
- fanout 测试用 monkeypatch 替换 engine.evaluate_tick（不依赖真实 DB 持久）
- reconnect 测试用 monkeypatch 替换 websockets.client.connect + asyncio.wait_for
"""
import asyncio
import json
from datetime import datetime

import pytest

# pytest-asyncio 0.16 不识别 asyncio_mode=auto；显式标记整个模块 async
pytestmark = pytest.mark.asyncio


# ─────────────── Fixtures ───────────────


@pytest.fixture
def db():
    """truncate strategy 系列表 + quote_snapshots 保隔离"""
    from server.db import SessionLocal
    from sqlalchemy import text
    s = SessionLocal()
    s.execute(text("DELETE FROM strategy_audit"))
    s.execute(text("DELETE FROM strategy_grid"))
    s.execute(text("DELETE FROM strategy_regime"))
    s.execute(text("DELETE FROM strategy"))
    s.execute(text("DELETE FROM quote_snapshots"))
    try:
        yield s
    finally:
        s.close()


def _make_hqserver_msg(stock_code, last_price):
    """构造 hqserver JSON 消息（quote_update 频道）"""
    return json.dumps({
        "type": "quote",
        "channel": "quote_update",
        "data": {
            "stock_code": stock_code,
            "last_price": last_price,
        },
    })


# ─────────────── Tests ───────────────


def test_parse_tick_extracts_stock_and_price():
    """hqserver quote_update JSON → {stock_code, last_price}"""
    from server.services.strategy.quote_consumer import QuoteConsumer
    raw = _make_hqserver_msg("600519.SH", 1820.5)
    tick = QuoteConsumer._parse_tick(raw)
    assert tick == {"stock_code": "600519.SH", "last_price": 1820.5}


def test_parse_tick_ignores_other_channels_and_bad_payloads():
    """非 quote_update / 非 quote type / 缺字段 / 非法 JSON → 静默返 None"""
    from server.services.strategy.quote_consumer import QuoteConsumer
    # 错误 channel
    raw1 = json.dumps({"type": "quote", "channel": "other",
                        "data": {"stock_code": "X", "last_price": 10.0}})
    assert QuoteConsumer._parse_tick(raw1) is None
    # 错误 type
    raw2 = json.dumps({"type": "other", "channel": "quote_update",
                        "data": {"stock_code": "X", "last_price": 10.0}})
    assert QuoteConsumer._parse_tick(raw2) is None
    # 缺 stock_code
    raw3 = json.dumps({"type": "quote", "channel": "quote_update",
                        "data": {"last_price": 10.0}})
    assert QuoteConsumer._parse_tick(raw3) is None
    # 缺 last_price
    raw4 = json.dumps({"type": "quote", "channel": "quote_update",
                        "data": {"stock_code": "X"}})
    assert QuoteConsumer._parse_tick(raw4) is None
    # 非法 JSON
    assert QuoteConsumer._parse_tick("not json{") is None
    # 非字符串
    assert QuoteConsumer._parse_tick(None) is None
    assert QuoteConsumer._parse_tick(12345) is None


async def test_fanout_routes_to_matching_engine(monkeypatch):
    """tick 命中 stock_code → engine.evaluate_tick 被调"""
    from server.services.strategy.quote_consumer import QuoteConsumer
    from server.services.strategy.engine import StrategyEngine

    qc = QuoteConsumer(url="ws://test")
    eng = StrategyEngine(strategy_id=1, stock_code="600519.SH")
    calls = []

    async def fake_evaluate_tick(tick, position_vol, base_volume, prev_close):
        calls.append({
            "tick": tick,
            "position_vol": position_vol,
            "base_volume": base_volume,
        })
    eng.evaluate_tick = fake_evaluate_tick
    qc._engines["600519.SH"] = eng

    tick = {"stock_code": "600519.SH", "last_price": 1820.5}
    await qc._fanout_tick(tick)

    assert len(calls) == 1
    assert calls[0]["tick"]["last_price"] == 1820.5
    # latest_price 记录（供 get_latest_price 查询）
    assert qc._latest_price["600519.SH"] == 1820.5
    # tick_count +1
    assert qc._tick_count == 1
    # last_tick_ts 已设置
    assert qc._last_tick_ts is not None


async def test_fanout_drops_tick_for_unsubscribed_stock():
    """未订阅 stock_code → 静默丢弃，evaluate_tick 不调，latest_price 仍记录"""
    from server.services.strategy.quote_consumer import QuoteConsumer
    from server.services.strategy.engine import StrategyEngine

    qc = QuoteConsumer(url="ws://test")
    eng = StrategyEngine(strategy_id=1, stock_code="600519.SH")
    calls = []

    async def fake_evaluate_tick(*args, **kwargs):
        calls.append(args)
    eng.evaluate_tick = fake_evaluate_tick
    qc._engines["600519.SH"] = eng

    # tick 给未订阅 stock
    tick = {"stock_code": "000001.SZ", "last_price": 10.0}
    await qc._fanout_tick(tick)

    assert calls == []
    # latest_price 仍然记录（业务可能需要查任意 stock 的最新价）
    assert qc._latest_price["000001.SZ"] == 10.0
    # tick_count +1（统计所有 tick）
    assert qc._tick_count == 1


async def test_load_engines_reads_active_and_injects_prev_close(db):
    """DB 读 status='active' strategies 建 engine + QuoteSnapshot 注入 prev_close"""
    from server.services.strategy.quote_consumer import QuoteConsumer
    from server.services.strategy import repository as repo
    from server.models.orm import QuoteSnapshot

    # 创建 2 个 active strategy
    s1 = repo.create_strategy(db, user_id=1, stock_code="600519.SH", type="general")
    s2 = repo.create_strategy(db, user_id=1, stock_code="000001.SZ", type="t0")
    db.commit()

    # 为 s1 灌 QuoteSnapshot (prev_close=1800.0)
    snap = QuoteSnapshot(
        stock_code="600519.SH",
        prev_close=1800.0,
        open_price=1810.0,
        high_price=1830.0,
        low_price=1805.0,
        last_price=1820.5,
        volume=1000,
        amount=1815000.0,
        ts=datetime.utcfromtimestamp(1234567890),
    )
    db.add(snap)
    db.commit()

    qc = QuoteConsumer(url="ws://test")
    await qc._load_engines()

    assert "600519.SH" in qc._engines
    assert "000001.SZ" in qc._engines
    assert qc._engine_id_map[s1.id] is qc._engines["600519.SH"]
    assert qc._engine_id_map[s2.id] is qc._engines["000001.SZ"]
    # s1 有 snapshot → prev_close 注入
    assert qc._engines["600519.SH"].prev_close == 1800.0
    # s2 没有 snapshot → prev_close 保持 None
    assert qc._engines["000001.SZ"].prev_close is None


async def test_reconnect_exponential_backoff(monkeypatch):
    """指数退避序列：1.0 → 2.0 → 4.0 → 8.0 → 16.0 → 30.0 (cap)"""
    from server.services.strategy.quote_consumer import QuoteConsumer

    delays = []

    async def fake_connect(*args, **kwargs):
        raise ConnectionError("simulated ws connect failure")

    async def fake_wait_for(coro, timeout=None):
        delays.append(timeout)
        # 关闭内部 _stop.wait() coroutine（不真等）
        try:
            coro.close()
        except Exception:
            pass
        # 采够 6 个样本后置 stop，循环退出
        if len(delays) >= 6:
            qc._stop.set()
        raise asyncio.TimeoutError

    # _connect 内部 `from websockets.client import connect` — 替换 websockets.client.connect
    monkeypatch.setattr("websockets.client.connect", fake_connect)
    # 替换 asyncio.wait_for — 捕获 delay 参数
    monkeypatch.setattr("asyncio.wait_for", fake_wait_for)

    qc = QuoteConsumer(url="ws://test:8765")
    await qc._connect()

    # 6 次失败：1.0 → 2.0 → 4.0 → 8.0 → 16.0 → 30.0（cap）
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]


async def test_singleton_get_and_close_lifecycle(monkeypatch):
    """get_quote_consumer / close_quote_consumer 模块级 singleton 生命周期"""
    from server.services.strategy import quote_consumer as qc_mod

    # 重置 module-level singleton
    monkeypatch.setattr(qc_mod, "_quote_consumer", None)

    # 让 start() 立即返回（避免真连 ws）
    async def fake_start(self):
        return None
    monkeypatch.setattr(qc_mod.QuoteConsumer, "start", fake_start)

    # 第一次调：创建 + 返回
    qc1 = await qc_mod.get_quote_consumer()
    assert qc1 is qc_mod._quote_consumer
    # 第二次调：返同一实例
    qc2 = await qc_mod.get_quote_consumer()
    assert qc1 is qc2

    # close：stop + 清空
    async def fake_stop(self):
        return None
    monkeypatch.setattr(qc_mod.QuoteConsumer, "stop", fake_stop)

    await qc_mod.close_quote_consumer()
    assert qc_mod._quote_consumer is None