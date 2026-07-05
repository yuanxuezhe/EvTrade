"""
test_grid.py — 网格决策 + 底仓保护单测（task 5）

覆盖：
- plan_buy：触发 / 不触发 / max_fires_reached
- plan_sell：6 种场景（含 spec 全部 4 个 Scenario + 2 个边界）
- plan_clear：全卖
- evaluate_grids：sell 优先 / clear_position 插入首位 / disabled 跳过
"""
import pytest


# ─────────────── Helpers ───────────────


def _make_grid(id_, direction, trigger_price, volume, max_fires=None, fired_count=0, enabled=True):
    """直接构造 StrategyGrid（不走 DB）"""
    from server.services.strategy.models import StrategyGrid
    return StrategyGrid(
        id=id_, regime_id=1,
        direction=direction,
        step_offset=0.0,
        trigger_price=trigger_price,
        volume=volume,
        max_fires=max_fires,
        fired_count=fired_count,
        enabled=enabled,
        priority=10,
    )


# ─────────────── plan_buy ───────────────


def test_plan_buy_triggered_when_below_trigger():
    from server.services.strategy.grid import plan_buy
    g = _make_grid(1, "buy", trigger_price=12.0, volume=100)
    a = plan_buy(g, current_price=11.95)  # ≤ 12.0 触发
    assert a is not None
    assert a.direction == "buy"
    assert a.volume == 100
    assert a.grid_id == 1
    assert a.reject_reason is None


def test_plan_buy_not_triggered_when_above():
    from server.services.strategy.grid import plan_buy
    g = _make_grid(1, "buy", trigger_price=12.0, volume=100)
    assert plan_buy(g, current_price=12.5) is None


def test_plan_buy_max_fires_reached_returns_reject_action():
    """max_fires 达上限时返 GridAction（reject），不返 None — engine 据此写 audit"""
    from server.services.strategy.grid import plan_buy
    g = _make_grid(1, "buy", trigger_price=12.0, volume=100, max_fires=3, fired_count=3)
    a = plan_buy(g, current_price=11.0)  # 价格触发但 fires 满
    assert a is not None
    assert a.reject_reason == "max_fires_reached"
    assert a.volume == 0


def test_plan_buy_disabled_returns_none():
    from server.services.strategy.grid import plan_buy
    g = _make_grid(1, "buy", trigger_price=12.0, volume=100, enabled=False)
    assert plan_buy(g, current_price=11.0) is None


# ─────────────── plan_sell ───────────────


def test_plan_sell_basic_above_floor():
    """spec Scenario: 持仓 500 / 底仓 100 / sell.volume=200 → 200"""
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200)
    a = plan_sell(g, position_vol=500, base_volume=100)
    assert a is not None
    assert a.volume == 200
    assert a.reject_reason is None


def test_plan_sell_at_floor_returns_reject_action():
    """spec Scenario: 持仓 100 / 底仓 100 → available=0 → reject"""
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200)
    a = plan_sell(g, position_vol=100, base_volume=100)
    assert a is not None
    assert a.reject_reason == "base_floor_protected"
    assert a.volume == 0


def test_plan_sell_partial_lot_rounding():
    """spec Scenario: 持仓 250 / 底仓 100 / vol=200 → available=150 → 整手 100"""
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200)
    a = plan_sell(g, position_vol=250, base_volume=100)
    assert a is not None
    assert a.volume == 100  # (150 // 100) * 100 = 100
    assert a.reject_reason is None


def test_plan_sell_lot_rounds_to_zero_returns_reject():
    """spec Scenario: 持仓 199 / 底仓 100 / vol=200 → available=99 → 整手 0 → reject"""
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200)
    a = plan_sell(g, position_vol=199, base_volume=100)
    assert a is not None
    assert a.reject_reason == "base_floor_protected"
    assert a.volume == 0


def test_plan_sell_larger_than_available_capped():
    """持仓 500 / 底仓 400 / vol=200 → available=100 → cap 至 100（整手）"""
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200)
    a = plan_sell(g, position_vol=500, base_volume=400)
    assert a is not None
    assert a.volume == 100  # min(200, 100) = 100, 整手不变


def test_plan_sell_max_fires_reached_returns_reject():
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200, max_fires=2, fired_count=2)
    a = plan_sell(g, position_vol=500, base_volume=100)
    assert a is not None
    assert a.reject_reason == "max_fires_reached"
    assert a.volume == 0


def test_plan_sell_disabled_returns_none():
    from server.services.strategy.grid import plan_sell
    g = _make_grid(1, "sell", trigger_price=12.5, volume=200, enabled=False)
    assert plan_sell(g, position_vol=500, base_volume=100) is None


# ─────────────── plan_clear ───────────────


def test_plan_clear_returns_full_position():
    from server.services.strategy.grid import plan_clear
    a = plan_clear(500)
    assert a.direction == "sell"
    assert a.volume == 500
    assert a.grid_id == -1
    assert a.reject_reason is None


def test_plan_clear_with_small_position():
    """清仓不受 LOT_SIZE 限制（即使 < 100 也全卖）"""
    from server.services.strategy.grid import plan_clear
    a = plan_clear(50)
    assert a.volume == 50


# ─────────────── evaluate_grids ───────────────


def test_evaluate_grids_sell_before_buy():
    """sell 必须排在 buy 之前（spec REQ-STRAT-006 防底仓被穿）

    📌 用 current_price 同时满足两边触发：sell trigger=12.0 (current>=trigger) + buy trigger=12.0 (current<=trigger)
    """
    from server.services.strategy.grid import evaluate_grids
    buy = _make_grid(1, "buy", trigger_price=12.0, volume=100)
    sell = _make_grid(2, "sell", trigger_price=12.0, volume=200)
    actions = evaluate_grids(
        grids=[buy, sell],
        current_price=12.0,
        position_vol=500, base_volume=100,
    )
    assert len(actions) == 2
    assert actions[0].direction == "sell"
    assert actions[1].direction == "buy"


def test_evaluate_grids_clear_position_inserted_first():
    from server.services.strategy.grid import evaluate_grids
    sell_grid = _make_grid(1, "sell", trigger_price=12.0, volume=200)
    actions = evaluate_grids(
        grids=[sell_grid],
        current_price=12.5,
        position_vol=500, base_volume=100,
        clear_position=True,
    )
    # clear_position=True → plan_clear(500) 在最前；sell_grid 也触发排在后
    assert len(actions) == 2
    assert actions[0].grid_id == -1  # plan_clear
    assert actions[0].volume == 500
    assert actions[1].grid_id == 1    # 普通 sell grid


def test_evaluate_grids_disabled_skipped():
    from server.services.strategy.grid import evaluate_grids
    buy_disabled = _make_grid(1, "buy", trigger_price=12.0, volume=100, enabled=False)
    sell_enabled = _make_grid(2, "sell", trigger_price=11.0, volume=200)
    actions = evaluate_grids(
        grids=[buy_disabled, sell_enabled],
        current_price=11.5, position_vol=500, base_volume=100,
    )
    # disabled buy 跳过 + sell 触发（11.5 >= 11.0）→ 只有 sell
    assert len(actions) == 1
    assert actions[0].direction == "sell"


def test_evaluate_grids_no_trigger_no_action():
    """价格不在任何网格触发区 → 无 action"""
    from server.services.strategy.grid import evaluate_grids
    buy = _make_grid(1, "buy", trigger_price=12.0, volume=100)
    sell = _make_grid(2, "sell", trigger_price=12.5, volume=200)
    # last_price=12.2 → 既不 ≤ 12.0 也不 ≥ 12.5
    actions = evaluate_grids(
        grids=[buy, sell],
        current_price=12.2, position_vol=500, base_volume=100,
    )
    assert actions == []


def test_evaluate_grids_clear_no_position_no_action():
    """clear_position=True 但 position_vol=0 → 不调 plan_clear"""
    from server.services.strategy.grid import evaluate_grids
    actions = evaluate_grids(
        grids=[], current_price=12.0,
        position_vol=0, base_volume=0,
        clear_position=True,
    )
    assert actions == []


def test_evaluate_grids_keeps_reject_actions_for_audit():
    """拒触发（非 None 含 reject_reason）保留在 actions 中（engine 据此写 audit）"""
    from server.services.strategy.grid import evaluate_grids
    # sell 但已到底仓 → 拒触发
    sell = _make_grid(1, "sell", trigger_price=12.0, volume=200)
    actions = evaluate_grids(
        grids=[sell],
        current_price=12.5, position_vol=100, base_volume=100,
    )
    assert len(actions) == 1
    assert actions[0].reject_reason == "base_floor_protected"


# ─────────────── Smoke ───────────────


def test_smoke_imports():
    from server.services.strategy.grid import (
        GridAction, plan_buy, plan_sell, plan_clear, evaluate_grids, LOT_SIZE,
    )
    assert LOT_SIZE == 100
    assert GridAction.__dataclass_params__.frozen is True