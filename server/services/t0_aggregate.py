"""
t0_aggregate.py — T0 敞口聚合 + 累计收益算法（facade 兼容垫片）

实现已拆分到：
- t0_fees: 费率与精度工具（_q2 / _q4 / calc_commission_and_tax / 共享常量）
- t0_pnl: 真实已实现算法（calc_realized_pnl）
- t0_aggregators: 分组合并（calc_net_exposure / aggregate_by_stock /
                   aggregate_by_day / aggregate_summary / apply_user_def_filter）

保留本 facade 是为了不破坏既有 import 路径
（`from server.services.t0_aggregate import ...` 在 api/t0_aggregate.py、
api/t0_stats.py、test_t0_aggregate.py 仍可用）。
"""
from server.services.t0_fees import (
    _BUY_TYPE,
    _FAILED_STATUS,
    _SELL_TYPE,
    _q2,
    _q4,
    calc_commission_and_tax,
)
from server.services.t0_pnl import calc_realized_pnl
from server.services.t0_aggregators import (
    _group_by_code,
    _order_count_stats,
    aggregate_by_day,
    aggregate_by_stock,
    aggregate_summary,
    apply_user_def_filter,
    calc_net_exposure,
)

__all__ = [
    # fees
    "calc_commission_and_tax",
    "_q2", "_q4",
    "_BUY_TYPE", "_SELL_TYPE", "_FAILED_STATUS",
    # pnl
    "calc_realized_pnl",
    # aggregators
    "calc_net_exposure",
    "_order_count_stats", "_group_by_code",
    "aggregate_by_stock", "aggregate_by_day", "aggregate_summary",
    "apply_user_def_filter",
]
