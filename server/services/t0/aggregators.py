"""
t0_aggregators.py — T0 聚合函数

提供：
- calc_net_exposure: 单标的敞口（废单不计入）
- aggregate_by_stock: 多标的聚合
- aggregate_by_day: 按日聚合
- aggregate_summary: 累计 + 胜率 + 回报率
- apply_user_def_filter: 按 user_def 标签过滤
- resolve_t0_user_defs: 解析 user_def 标签（含 T0 策略单）— task 8 (strategy_trade)
"""
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session


from server.models.orm import Order, Trade

from server.services.t0.fees import (
    _BUY_TYPE,
    _SELL_TYPE,
    _q2,
    _q4,
)
from server.services.t0.pnl import calc_realized_pnl


def calc_net_exposure(
    orders: List[Order], trades: List[Trade]
) -> Tuple[int, int, int, float, float]:
    """单标的敞口 = 买单量 - 卖单量

    仅计入有效委托/成交（废单 Order.status='55' 不计入）
    注意：trades 已是该 stock_code 的子集

    Args:
        orders: 该 stock_code 当日 Order 列表
        trades: 该 stock_code 当日 Trade 列表

    Returns:
        (net_volume, buy_vol, sell_vol, buy_amt, sell_amt)
        net_volume: 正=净买入敞口，负=净卖出敞口
    """
    buy_vol = 0
    sell_vol = 0
    buy_amt = 0.0
    sell_amt = 0.0
    for t in trades:
        if t.order_type == _BUY_TYPE:
            buy_vol += int(t.volume or 0)
            buy_amt += float(t.price or 0) * int(t.volume or 0)
        elif t.order_type == _SELL_TYPE:
            sell_vol += int(t.volume or 0)
            sell_amt += float(t.price or 0) * int(t.volume or 0)
    return buy_vol - sell_vol, buy_vol, sell_vol, buy_amt, sell_amt


def _order_count_stats(orders: List[Order]) -> Tuple[int, int]:
    """委托笔数 + 待报/已报笔数"""
    total = len(orders)
    open_cnt = sum(
        1 for o in orders if o.status in ("48", "49", "50", "51")
    )
    return total, open_cnt


def _group_by_code(trades: List[Trade]) -> Dict[str, List[Trade]]:
    """trades 按 stock_code 分组"""
    out: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        out[t.stock_code].append(t)
    return out


def aggregate_by_stock(
    trades: List[Trade],
    orders: List[Order],
    positions: Dict[str, dict],
    fee_cfg: dict,
    include_unrealized: bool = True,
) -> List[Dict]:
    """按 stock_code 聚合

    Args:
        trades: 跨所有 stock_code 的 Trade 列表
        orders: 跨所有 stock_code 的 Order 列表
        positions: {stock_code: dict}，提供 cost_basis
        fee_cfg: 费率
        include_unrealized: 是否算浮动盈亏（仅参考用）

    Returns:
        List[{stock_code, buy_vol, sell_vol, net_volume, buy_amt, sell_amt,
              net_amount, realized_pnl, commission, stamp_tax, order_count,
              trade_count, open_order_count, position_volume, cost_basis}]
        按 abs(net_amount) 降序
    """
    by_stock: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        by_stock[t.stock_code].append(t)
    by_stock_orders: Dict[str, List[Order]] = defaultdict(list)
    for o in orders:
        by_stock_orders[o.stock_code].append(o)

    rows = []
    for code, stock_trades in by_stock.items():
        stock_orders = by_stock_orders.get(code, [])
        net_vol, buy_vol, sell_vol, buy_amt, sell_amt = calc_net_exposure(
            stock_orders, stock_trades
        )
        sell_trades = [t for t in stock_trades if t.order_type == _SELL_TYPE]
        pos = positions.get(code)
        cost_basis = float(pos.cost_price) if pos else 0.0
        realized, commission, stamp_tax = calc_realized_pnl(
            sell_trades, cost_basis, fee_cfg
        )
        order_count, open_order_count = _order_count_stats(stock_orders)
        rows.append({
            "stock_code": code,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "net_volume": net_vol,
            "buy_amount": _q2(buy_amt),
            "sell_amount": _q2(sell_amt),
            "net_amount": _q2(buy_amt - sell_amt),
            "realized_pnl": realized,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "order_count": order_count,
            "trade_count": len(stock_trades),
            "open_order_count": open_order_count,
            "position_volume": int(pos.vol) if pos and pos.vol else 0,
            "cost_basis": _q2(cost_basis),
        })

    rows.sort(key=lambda r: abs(r["net_amount"]), reverse=True)
    return rows


def aggregate_by_day(
    trades: List[Trade],
    positions: Dict[str, dict],
    fee_cfg: dict,
) -> List[Dict]:
    """按交易日聚合（跨标的）

    Args:
        trades: 全部 Trade 列表
        positions: {stock_code: dict}，提供 cost_basis（用当前快照）
        fee_cfg: 费率

    Returns:
        List[{trd_date, realized_pnl, buy_amount, sell_amount, trade_count, stock_count}]
        按 trd_date 升序
    """
    by_day: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        by_day[t.trd_date].append(t)

    rows = []
    for trd, day_trades in by_day.items():
        sell_trades = [t for t in day_trades if t.order_type == _SELL_TYPE]
        realized_total = 0.0
        commission_total = 0.0
        stamp_tax_total = 0.0
        for code, code_trades in _group_by_code(sell_trades).items():
            pos = positions.get(code)
            cost_basis = float(pos.cost_price) if pos else 0.0
            r, c, st = calc_realized_pnl(code_trades, cost_basis, fee_cfg)
            realized_total += r
            commission_total += c
            stamp_tax_total += st
        buy_amt = sum(
            float(t.price or 0) * int(t.volume or 0)
            for t in day_trades if t.order_type == _BUY_TYPE
        )
        sell_amt = sum(
            float(t.price or 0) * int(t.volume or 0)
            for t in day_trades if t.order_type == _SELL_TYPE
        )
        rows.append({
            "trd_date": trd,
            "realized_pnl": _q2(realized_total),
            "buy_amount": _q2(buy_amt),
            "sell_amount": _q2(sell_amt),
            "trade_count": len(day_trades),
            "stock_count": len(set(t.stock_code for t in day_trades)),
            "commission": _q2(commission_total),
            "stamp_tax": _q2(stamp_tax_total),
        })
    rows.sort(key=lambda r: r["trd_date"])
    return rows


def aggregate_summary(
    by_day: List[Dict],
    by_stock: List[Dict],
    orders: List[Order],
) -> Dict:
    """累计汇总

    Returns:
        {total_realized, total_commission, total_stamp_tax,
         total_buy_amount, total_sell_amount,
         win_days, total_days, win_rate, return_rate,
         trade_count, order_count, stocks_traded}
    """
    total_realized = sum(d["realized_pnl"] for d in by_day)
    total_buy = sum(d["buy_amount"] for d in by_day)
    total_sell = sum(d["sell_amount"] for d in by_day)
    total_commission = sum(d.get("commission", 0.0) for d in by_day)
    total_stamp_tax = sum(d.get("stamp_tax", 0.0) for d in by_day)
    total_trade_count = sum(d["trade_count"] for d in by_day)
    win_days = sum(1 for d in by_day if d["realized_pnl"] > 0)
    total_days = len(by_day)
    win_rate = (win_days / total_days) if total_days > 0 else 0.0
    return_rate = (total_realized / total_buy) if total_buy > 0 else 0.0
    return {
        "total_realized": _q2(total_realized),
        "total_commission": _q2(total_commission),
        "total_stamp_tax": _q2(total_stamp_tax),
        "total_buy_amount": _q2(total_buy),
        "total_sell_amount": _q2(total_sell),
        "win_days": win_days,
        "total_days": total_days,
        "win_rate": _q4(win_rate),
        "return_rate": _q4(return_rate),
        "trade_count": total_trade_count,
        "order_count": len(orders),
        "stocks_traded": len(by_stock),
    }


def apply_user_def_filter(
    orders: List[Order],
    trades: List[Trade],
    user_def: str,
    db: Optional[Session] = None,
) -> Tuple[List[Order], List[Trade]]:
    """按 user_def 过滤（空字符串 = 全部）

    Args:
        orders: 全部订单
        trades: 全部成交
        user_def: 要过滤的标签（'T0' / '' = 全部 / 其他 = 字面匹配）
        db: 可选 — 传入时扩展支持 'T0' 策略单（user_def = str(strategy.id) where type='t0'）

    Returns:
        (filtered_orders, filtered_trades)
    """
    if not user_def:
        return orders, trades
    if db is not None:
        allowed = resolve_t0_user_defs(db, user_def)
    else:
        allowed = {user_def}
    f_orders = [o for o in orders if o.user_def in allowed]
    order_nos = {o.order_no for o in f_orders}
    f_trades = [t for t in trades if t.order_no in order_nos]
    return f_orders, f_trades


def resolve_t0_user_defs(db: Session, user_def: str) -> Optional[Set[str]]:
    """解析 user_def 标签，扩展支持 T0 策略单（change strategy_trade task 8）

    Args:
        db: SQLAlchemy session
        user_def: 标签值

    Returns:
        None = 不限（user_def 空字符串）
        Set[str] = 允许的 user_def 值集合
            - 'T0' → {'T0'} ∪ {所有 type='t0' 的 strategy id as str}
            - 其他 → {user_def} 单值
    """
    if not user_def:
        return None
    if user_def == 'T0':
        from server.tables import Strategy
        t0_ids = {
            str(s.id) for s in Strategy.query_all() if s.type == 't0'
        }
        return {'T0'} | t0_ids
    return {user_def}
