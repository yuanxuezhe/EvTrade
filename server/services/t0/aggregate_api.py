"""
t0/aggregate_api.py — T0 敞口聚合 + 累计收益算法 统一入口

实现拆分到同模块 3 个子文件：
- t0.fees: 费率与精度工具（_q2 / _q4 / calc_commission_and_tax / 共享常量）
- t0.pnl: 真实已实现算法（calc_realized_pnl）
- t0.aggregators: 分组合并（calc_net_exposure / aggregate_by_stock /
                   aggregate_by_day / aggregate_summary / apply_user_def_filter）

调用方应从本 facade 统一导入，避免分散到子文件。
"""
from server.services.t0.fees import (
    _BUY_TYPE,
    _FAILED_STATUS,
    _SELL_TYPE,
    _q2,
    _q4,
    calc_commission_and_tax,
)
from server.services.t0.pnl import calc_realized_pnl
from server.services.t0.aggregators import (
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
