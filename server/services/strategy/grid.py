"""
strategy — 网格决策（含底仓保护 + 清仓）（change strategy_trade task 5）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-004 / 005 / 006
📌 核心不变式：所有非 clear_position=True 路径下，position.vol ≥ strategy.base_volume 恒成立
📌 4 函数：plan_buy / plan_sell / plan_clear / evaluate_grids
📌 evaluate_grids 串 sell 在前 buy 在后排序（防底仓被穿）
📌 纯函数：返 GridAction，不调 ord_stk / DB / WS；engine (task 6) 负责后续串联
"""
from dataclasses import dataclass
from typing import List, Optional

from server.services.strategy.models import StrategyGrid


# ─────────────── 常量 ───────────────

LOT_SIZE = 100  # A 股整手单位（科创板 200，深市 100；v1 默认 100）


# ─────────────── GridAction 数据结构 ───────────────


@dataclass(frozen=True)
class GridAction:
    """evaluate_grids 输出的动作项（engine 据此下单 + 写 audit + WS broadcast）

    📌 direction='buy' / 'sell'
    📌 volume=0 表示拒触发（reject_reason 非空）
    📌 reject_reason 取值：
       - 'base_floor_protected'（plan_sell 受底仓保护限制）
       - 'max_fires_reached'（已达 max_fires 上限）
       - None（正常触发）
    """
    direction: str
    volume: int
    trigger_price: float
    grid_id: int
    reject_reason: Optional[str] = None


# ─────────────── 单 grid 决策 ───────────────


def _is_max_fires_reached(grid: StrategyGrid) -> bool:
    """fired_count >= max_fires (when max_fires is not None)"""
    if grid.max_fires is None:
        return False
    return (grid.fired_count or 0) >= grid.max_fires


def plan_buy(grid: StrategyGrid, current_price: float) -> Optional[GridAction]:
    """买单决策：current_price ≤ trigger_price 触发；否则不触发

    📌 拒触发原因：max_fires_reached（fired_count 达上限）
    📌 触发：返 GridAction(direction='buy', volume=grid.volume)
    """
    if not grid.enabled:
        return None
    if _is_max_fires_reached(grid):
        return GridAction(
            direction="buy", volume=0,
            trigger_price=grid.trigger_price or 0.0, grid_id=grid.id,
            reject_reason="max_fires_reached",
        )
    if current_price <= grid.trigger_price:
        return GridAction(
            direction="buy", volume=grid.volume,
            trigger_price=grid.trigger_price or 0.0, grid_id=grid.id,
        )
    return None


def plan_sell(
    grid: StrategyGrid,
    position_vol: int,
    base_volume: int,
) -> Optional[GridAction]:
    """卖单决策：含底仓保护 + 整手取整

    📌 决策树：
       1. 触发条件由 caller 预过滤：current_price >= trigger_price（这里不再判断）
       2. max_fires_reached → reject
       3. available_to_sell = max(0, position_vol - base_volume)
          ≤ 0 → reject(base_floor_protected)
       4. sell_vol = min(grid.volume, available)
          整手向下：(sell_vol // LOT_SIZE) * LOT_SIZE
          ≤ 0 → reject(base_floor_protected)
       5. 触发：返 GridAction(direction='sell', volume=sell_vol)
    """
    if not grid.enabled:
        return None
    if _is_max_fires_reached(grid):
        return GridAction(
            direction="sell", volume=0,
            trigger_price=grid.trigger_price or 0.0, grid_id=grid.id,
            reject_reason="max_fires_reached",
        )
    available = max(0, position_vol - base_volume)
    if available <= 0:
        return GridAction(
            direction="sell", volume=0,
            trigger_price=grid.trigger_price or 0.0, grid_id=grid.id,
            reject_reason="base_floor_protected",
        )
    sell_vol = min(grid.volume, available)
    sell_vol = (sell_vol // LOT_SIZE) * LOT_SIZE  # 整手向下
    if sell_vol <= 0:
        return GridAction(
            direction="sell", volume=0,
            trigger_price=grid.trigger_price or 0.0, grid_id=grid.id,
            reject_reason="base_floor_protected",
        )
    return GridAction(
        direction="sell", volume=sell_vol,
        trigger_price=grid.trigger_price or 0.0, grid_id=grid.id,
    )


def plan_clear(position_vol: int) -> GridAction:
    """清仓（regime.clear_position=True 时调）：全卖不整手取整

    📌 grid_id = -1 表示非 grid 触发，是 regime 级别的 clear
    📌 不受 LOT_SIZE 限制（即使 50 股也全卖）
    """
    return GridAction(
        direction="sell", volume=position_vol,
        trigger_price=0.0, grid_id=-1,
    )


# ─────────────── 多 grid 编排 ───────────────


def evaluate_grids(
    grids: List[StrategyGrid],
    current_price: float,
    position_vol: int,
    base_volume: int,
    clear_position: bool = False,
) -> List[GridAction]:
    """遍历 enabled grids → 决策 → sell 优先排序

    📌 排序：sell 在前 buy 在后（spec REQ-STRAT-006 §sell 优先于 buy 防底仓穿）
    📌 clear_position=True → 在 sell 队列最前插 plan_clear(position_vol)
    📌 拒触发（非 None 含 reject_reason）也保留在 actions 中，让 engine 据此写 audit
    📌 grid.disabled 或价格未达触发线 → 不入 actions
    📌 触发判断：current_price <= trigger_price(buy) / current_price >= trigger_price(sell)
    """
    actions: List[GridAction] = []

    # 1. 清仓（clear_position 路径优先于普通 grid）
    if clear_position and position_vol > 0:
        actions.append(plan_clear(position_vol))

    # 2. 遍历所有 enabled grids
    for g in grids:
        if not g.enabled:
            continue
        # 价格过滤：sell 要求 current_price >= trigger；buy 要求 current_price <= trigger
        if g.direction == "buy":
            if current_price > g.trigger_price:
                continue
            a = plan_buy(g, current_price)
        elif g.direction == "sell":
            if current_price < g.trigger_price:
                continue
            a = plan_sell(g, position_vol, base_volume)
        else:
            a = None
        if a is not None:
            actions.append(a)

    # 3. 排序：sell 在前 buy 在后；同方向保留原顺序（按 grid.priority DESC, id ASC 已在 DB 层排好）
    # Python sorted 是稳定排序
    actions.sort(key=lambda a: 0 if a.direction == "sell" else 1)
    return actions


__all__ = ["GridAction", "plan_buy", "plan_sell", "plan_clear", "evaluate_grids", "LOT_SIZE"]