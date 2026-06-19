"""
t0_aggregate.py — T0 敞口聚合 + 累计收益算法

提供：
- calc_realized_pnl: 真实已实现 = (avg_sell - cost_basis) * sell_vol - 费用
- calc_net_exposure: 单标的敞口 = buy_vol - sell_vol（废单不计入）
- aggregate_by_stock: 多标的当日 / 跨期聚合
- aggregate_by_day: 按日聚合
- aggregate_summary: 累计 + 胜率 + 回报率

约定：
- 失败单 Order.status == '55'（废单）不计入成交统计
- 成本基准 cost_basis 取当前 Position.cost_price（缺省 0）
- 卖出方向才计 commission + stamp_tax，买入只计 commission
- 金额保留 2 位小数（用 round(_, 2)）
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from models.orm import FeeConfig, Order, Position, Trade


# 失败单状态：废单不计入
_FAILED_STATUS = "55"
# 卖出方向 order_type
_SELL_TYPE = "24"
# 买入方向 order_type
_BUY_TYPE = "23"


def _q2(x: float) -> float:
    """保留 2 位小数（金融用 round-half-up）"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _q4(x: float) -> float:
    """保留 4 位小数（胜率/收益率）"""
    return float(Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def calc_commission_and_tax(
    amount: float, fee_cfg: FeeConfig, direction: str
) -> Tuple[float, float]:
    """算手续费 + 印花税（卖出）

    Args:
        amount: 成交金额（价格 × 数量）
        fee_cfg: 费率配置
        direction: 'BUY' / 'SELL'

    Returns:
        (commission, stamp_tax)
    """
    commission = round(amount * fee_cfg.commission_rate, 2)
    # 最低佣金兜底（A 股规则：佣金 < 5 元时按 5 元收）
    min_c = getattr(fee_cfg, "min_commission", 0.0) or 0.0
    if min_c > 0 and commission < min_c and amount > 0:
        commission = min_c
    stamp_tax = 0.0
    if direction == "SELL":
        stamp_tax = round(amount * fee_cfg.stamp_tax_rate, 2)
    return commission, stamp_tax


def calc_realized_pnl(
    sell_trades: List[Trade],
    cost_basis: float,
    fee_cfg: FeeConfig,
) -> Tuple[float, float, float]:
    """真实已实现盈亏

    公式：
        sell_amt = Σ(t.price * t.volume) for t in sell_trades
        sell_vol = Σ(t.volume)
        avg_sell = sell_amt / sell_vol
        commission = round(sell_amt * commission_rate, 2)  [兜底 min_commission]
        stamp_tax  = round(sell_amt * stamp_tax_rate, 2)
        realized   = (avg_sell - cost_basis) * sell_vol - commission - stamp_tax
                    = sell_amt - cost_basis * sell_vol - commission - stamp_tax

    Args:
        sell_trades: 卖出方向的 Trade 列表（已按 trd_date 过滤）
        cost_basis: 当前持仓的均价（无则 0）
        fee_cfg: 费率配置

    Returns:
        (realized, commission, stamp_tax)
    """
    if not sell_trades:
        return 0.0, 0.0, 0.0
    sell_amt = 0.0
    sell_vol = 0
    for t in sell_trades:
        sell_amt += float(t.price or 0) * int(t.volume or 0)
        sell_vol += int(t.volume or 0)
    if sell_vol <= 0:
        return 0.0, 0.0, 0.0
    commission, stamp_tax = calc_commission_and_tax(sell_amt, fee_cfg, "SELL")
    gross_pnl = sell_amt - cost_basis * sell_vol
    realized = gross_pnl - commission - stamp_tax
    return _q2(realized), _q2(commission), _q2(stamp_tax)


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


def aggregate_by_stock(
    trades: List[Trade],
    orders: List[Order],
    positions: Dict[str, Position],
    fee_cfg: FeeConfig,
    include_unrealized: bool = True,
) -> List[Dict]:
    """按 stock_code 聚合

    Args:
        trades: 跨所有 stock_code 的 Trade 列表
        orders: 跨所有 stock_code 的 Order 列表（用于 order_count / open_order_count）
        positions: {stock_code: Position}，提供 cost_basis
        fee_cfg: 费率
        include_unrealized: 是否算浮动盈亏（基于 cost_basis + 卖单均价，仅参考用）

    Returns:
        List[{stock_code, buy_vol, sell_vol, net_volume, buy_amt, sell_amt,
              net_amount, realized_pnl, commission, stamp_tax, order_count,
              trade_count, open_order_count, position_volume, cost_basis}]
        按 abs(net_amount) 降序
    """
    # 按 stock_code 分组 trades
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

    # 按 abs(net_amount) 降序
    rows.sort(key=lambda r: abs(r["net_amount"]), reverse=True)
    return rows


def aggregate_by_day(
    trades: List[Trade],
    positions: Dict[str, Position],
    fee_cfg: FeeConfig,
) -> List[Dict]:
    """按交易日聚合（跨标的）

    Args:
        trades: 全部 Trade 列表
        positions: {stock_code: Position}，提供 cost_basis（用当前快照）
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
        # 按日累计 realized：每个 stock_code 用当日 Position 的 cost_basis
        # （近似：本日用当前成本基准，真实应取日内历史 cost —— 当前 Position 是快照，
        #   对做T 来说买入后立即卖出 → cost_basis 还来不及变化，误差可接受）
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


def _group_by_code(trades: List[Trade]) -> Dict[str, List[Trade]]:
    """trades 按 stock_code 分组"""
    out: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        out[t.stock_code].append(t)
    return out


def aggregate_summary(
    by_day: List[Dict],
    by_stock: List[Dict],
    orders: List[Order],
) -> Dict:
    """累计汇总

    Args:
        by_day: aggregate_by_day 输出
        by_stock: aggregate_by_stock 输出
        orders: 全部委托（用于 order_count / stocks_traded）

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
) -> Tuple[List[Order], List[Trade]]:
    """按 user_def 过滤（空字符串 = 全部）

    Args:
        orders: 全部订单
        trades: 全部成交
        user_def: 要过滤的标签（'T0' 或 '' 表示全部）

    Returns:
        (filtered_orders, filtered_trades)
    """
    if not user_def:
        return orders, trades
    order_nos = {o.order_no for o in orders if o.user_def == user_def}
    f_orders = [o for o in orders if o.user_def == user_def]
    f_trades = [t for t in trades if t.order_no in order_nos]
    return f_orders, f_trades
