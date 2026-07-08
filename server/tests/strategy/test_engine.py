"""
test_engine.py — StrategyEngine 评估入口单测（task 6）

覆盖：
- no_match: 无 active flag → audit 'no_match'
- regime_switch: 切换 regime → audit 'regime_switch' + WS broadcast
- regime_cooldown: 冷却期阻止切换 → audit 'regime_cooldown'
- no_action: 命中 regime 但网格不触发 → audit 'no_action'
- buy trigger: 触发 buy → INSERT Order + ord_stk + audit 'grid_buy'
- sell floor protection: 触发 sell 但底仓保护 → audit reject='base_floor_protected'，不下单
- clear position: clear_position=True → plan_clear + audit 'clear'
- sell before buy: 单 tick 内 sell 优先

Mock 策略：
- monkeypatch `server.services.strategy.engine.ord_stk` 为 fake async
- monkeypatch `server.services.strategy.engine.ws_manager.broadcast` 为 fake async
"""
import pytest

pytestmark = pytest.mark.asyncio

# 业务 import 必须在 pytestmark 后 (pytest 约定, pytest-asyncio 0.16 不识别 asyncio_mode=auto)
from server.services.strategy import repository as repo  # noqa: E402  (pytestmark 强制)


# ─────────────── Fixtures ───────────────


@pytest.fixture
def db():
    """每个 test 独立 Session（truncate strategy 系列表保隔离）"""
    from server.db import SessionLocal
    from sqlalchemy import text
    s = SessionLocal()
    # 注意：truncate 顺序：audit → grid → regime → strategy → orders
    s.execute(text("DELETE FROM strategy_audit"))
    s.execute(text("DELETE FROM strategy_grid"))
    s.execute(text("DELETE FROM strategy_regime"))
    s.execute(text("DELETE FROM strategy"))
    s.execute(text("DELETE FROM orders"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def mock_ord_stk(monkeypatch):
    """替换 ord_stk：fake async 函数记录调用 + 返回 OK"""
    calls = []
    async def fake(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return {"code": 0, "msg": "OK", "list": [{"order_id": "broker-1"}]}
    monkeypatch.setattr("server.services.strategy.engine.ord_stk", fake)
    return calls


@pytest.fixture
def mock_ws_broadcast(monkeypatch):
    """替换 ws_manager.broadcast：fake async 函数记录调用"""
    calls = []
    async def fake(channel, message, **kwargs):
        calls.append({"channel": channel, "message": message})
    monkeypatch.setattr("server.services.strategy.engine.ws_manager.broadcast", fake)
    return calls


def _make_strategy_with_regime(db, **regime_kwargs):
    """构造 strategy + 1 个 regime（grids 可选）"""
    s = repo.create_strategy(db, user_id=1, stock_code="600519.SH", type="general")
    db.commit()
    db.refresh(s)
    regime_kwargs.setdefault("name", "R1")
    regime_kwargs.setdefault("priority", 10)
    r = repo.create_regime(db, s.id, **regime_kwargs)
    db.commit()
    db.refresh(r)
    return s, r


# ─────────────── Tests ───────────────


async def test_engine_no_match_writes_no_match_audit(db, mock_ord_stk, mock_ws_broadcast):
    """无 active flag → audit 'no_match'，不下单"""
    from server.services.strategy.engine import StrategyEngine
    s, _ = _make_strategy_with_regime(db, required_flags=["ma_bullish"])
    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    tick = {"last_price": 10.0, "volume": 100}
    result = await eng.evaluate_tick(
        tick, position_vol=0, base_volume=100,
        prev_close=None, now_ts=1000.0, trd_date="20260705",
    )

    assert result.matched_regime_id is None
    # audit 表里应该有 1 行 no_match
    rows = repo.list_audits(db, s.id, "20260705")
    assert len(rows) == 1
    assert rows[0].trigger_type == "no_match"
    # 没下任何单
    assert mock_ord_stk == []


async def test_engine_match_regime_no_grid_trigger(db, mock_ord_stk, mock_ws_broadcast):
    """命中 regime 但价格不触发网格 → audit 'regime_switch' + 'no_action'"""
    from server.services.strategy.engine import StrategyEngine
    s, r = _make_strategy_with_regime(
        db, required_flags=[], exclude_flags=[],
        grids=[{"direction": "buy", "trigger_price": 9.0, "volume": 100}],
    )
    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    tick = {"last_price": 10.0, "volume": 100}  # > trigger_price 9.0 → 不触发
    result = await eng.evaluate_tick(
        tick, position_vol=0, base_volume=100,
        prev_close=None, now_ts=1000.0, trd_date="20260705",
    )

    assert result.matched_regime_id == r.id
    rows = repo.list_audits(db, s.id, "20260705")
    # 首次 tick 触发 regime_switch（None → R1）+ no_action（网格不达）
    types = [r.trigger_type for r in rows]
    assert "regime_switch" in types
    assert "no_action" in types
    assert mock_ord_stk == []


async def test_engine_buy_grid_trigger_places_order(db, mock_ord_stk, mock_ws_broadcast):
    """触发 buy → 写 audit + INSERT Order + ord_stk + audit grid_buy + WS broadcast"""
    from server.services.strategy.engine import StrategyEngine
    s, r = _make_strategy_with_regime(
        db, required=[],
        grids=[{"direction": "buy", "trigger_price": 10.0, "volume": 100}],
    )
    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    tick = {"last_price": 9.5, "volume": 100}  # ≤ 10.0 触发
    await eng.evaluate_tick(
        tick, position_vol=0, base_volume=100,
        prev_close=None, now_ts=1000.0, trd_date="20260705",
    )

    assert len(mock_ord_stk) == 1
    assert mock_ord_stk[0]["kwargs"]["volume"] == 100
    # Order 应写入 DB
    from server.models.orm import Order
    order = db.query(Order).filter_by(user_def=str(s.id)).first()
    assert order is not None
    assert order.volume == 100
    assert order.order_type == "23"  # buy
    # audit 应至少 1 行 grid_buy
    rows = repo.list_audits(db, s.id, "20260705")
    assert any(row.trigger_type == "grid_buy" for row in rows)
    # WS 广播 grid_triggered
    assert any(call["channel"] == "strategy_update" and call["message"]["type"] == "grid_triggered"
               for call in mock_ws_broadcast)


async def test_engine_sell_floor_protected_no_order(db, mock_ord_stk, mock_ws_broadcast):
    """触发 sell 但已到底仓 → audit reject='base_floor_protected'，不下单"""
    from server.services.strategy.engine import StrategyEngine
    s, r = _make_strategy_with_regime(
        db, required=[],
        grids=[{"direction": "sell", "trigger_price": 10.0, "volume": 200}],
    )
    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    tick = {"last_price": 11.0, "volume": 100}  # ≥ 10.0 触发
    # 持仓 100 / 底仓 100 → available=0 → 拒触发
    await eng.evaluate_tick(
        tick, position_vol=100, base_volume=100,
        prev_close=None, now_ts=1000.0, trd_date="20260705",
    )

    # 没下任何单（拒触发）
    assert mock_ord_stk == []
    # audit 应有 grid_sell + reject_reason
    rows = repo.list_audits(db, s.id, "20260705")
    assert any(row.reject_reason == "base_floor_protected" for row in rows)


async def test_engine_clear_position_dumps_all(db, mock_ord_stk, mock_ws_broadcast):
    """clear_position=True → plan_clear 全卖（不受 LOT_SIZE 限制）"""
    from server.services.strategy.engine import StrategyEngine
    s, r = _make_strategy_with_regime(db, required=[], clear_position=True)
    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    tick = {"last_price": 10.0, "volume": 100}
    await eng.evaluate_tick(
        tick, position_vol=150, base_volume=100,
        prev_close=None, now_ts=1000.0, trd_date="20260705",
    )

    # 1 个 plan_clear action → 1 次 ord_stk
    assert len(mock_ord_stk) == 1
    assert mock_ord_stk[0]["kwargs"]["volume"] == 150  # 全卖 position_vol
    assert mock_ord_stk[0]["kwargs"]["order_type"] == "24"  # sell


async def test_engine_regime_cooldown_blocks_switch(db, mock_ord_stk, mock_ws_broadcast):
    """cooldown 内不切换 regime → audit 'regime_cooldown'"""
    from server.services.strategy.engine import StrategyEngine
    s = repo.create_strategy(db, user_id=1, stock_code="X.SH")
    db.commit()
    # 创建两个 regime
    r1 = repo.create_regime(db, s.id, name="R1", priority=10, required_flags=["ma_bullish"])
    repo.create_regime(db, s.id, name="R2", priority=20, required_flags=["ma_bullish"])
    db.commit()

    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    # 第一次 tick：buffer.append + 喂入 ma_bullish + 触发 R2（高 priority）
    # 但 ma_bullish 需要 buffer 满 20 ticks
    for i in range(25):
        prices = [10.0 + 0.5 * i for i in range(25)]
        eng.buffer.append({"last_price": prices[i], "volume": 100})
    eng.last_switch_ts = 1000.0
    eng.last_regime = r1  # 已经激活 R1

    tick = {"last_price": 22.0, "volume": 100}
    # now=1050 → cooldown=300 → diff=50 < 300 → 阻止切换
    result = await eng.evaluate_tick(
        tick, position_vol=0, base_volume=100,
        prev_close=None, now_ts=1050.0, trd_date="20260705",
    )

    assert result.regime_cooldown_blocked is True
    rows = repo.list_audits(db, s.id, "20260705")
    assert any(row.trigger_type == "regime_cooldown" for row in rows)


async def test_engine_sell_before_buy_in_actions(db, mock_ord_stk, mock_ws_broadcast):
    """单 tick 内 sell + buy 同时触发 → ord_stk 调用顺序 sell 在前 buy 在后"""
    from server.services.strategy.engine import StrategyEngine
    s, r = _make_strategy_with_regime(
        db, required=[],
        grids=[
            {"direction": "buy", "trigger_price": 10.0, "volume": 100, "priority": 10},
            {"direction": "sell", "trigger_price": 10.0, "volume": 200, "priority": 10},
        ],
    )
    eng = StrategyEngine(strategy_id=s.id, stock_code=s.stock_code)

    tick = {"last_price": 10.0, "volume": 100}  # 同时满足买卖触发
    await eng.evaluate_tick(
        tick, position_vol=500, base_volume=100,  # 持仓 500/底仓 100，sell 可卖 400
        prev_close=None, now_ts=1000.0, trd_date="20260705",
    )

    # ord_stk 调用顺序：sell 先（防底仓穿），buy 后
    assert len(mock_ord_stk) == 2
    assert mock_ord_stk[0]["kwargs"]["order_type"] == "24"  # sell
    assert mock_ord_stk[1]["kwargs"]["order_type"] == "23"  # buy


async def test_engine_smoke_imports():
    """sanity: import 不报错"""
    from server.services.strategy.engine import (
        EvaluateResult, STRATEGY_WS_CHANNEL,
    )
    assert STRATEGY_WS_CHANNEL == "strategy_update"
    assert EvaluateResult(strategy_id=1).strategy_id == 1