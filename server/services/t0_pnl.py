"""
t0_pnl.py — T0 真实已实现盈亏算法

公式：
    sell_amt = Σ(t.price * t.volume) for t in sell_trades
    sell_vol = Σ(t.volume)
    avg_sell = sell_amt / sell_vol
    realized = (avg_sell - cost_basis) * sell_vol - commission - stamp_tax
             = sell_amt - cost_basis * sell_vol - commission - stamp_tax
"""
from typing import List, Tuple

from server.models.orm import FeeConfig, Trade

from server.services.t0_fees import calc_commission_and_tax, _q2


def calc_realized_pnl(
    sell_trades: List[Trade],
    cost_basis: float,
    fee_cfg: FeeConfig,
) -> Tuple[float, float, float]:
    """真实已实现盈亏

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
