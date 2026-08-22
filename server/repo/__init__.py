"""
server.repo — 仓库层

按表聚合的 CRUD 函数 + 表级业务方法（如 next_order_no / infer_order_status）。

依赖方向：本层仅可 import `server.tables.*` / `server.infra.db` / `server.utils.*`。
禁止 import 上层（api / services / rpc）。

模块：
- orders.py        — orders 表 + order_no_seq 表（含 next_order_no / infer_order_status）
- trades.py        — trades 表 CRUD
- positions.py     — positions 表 CRUD
- assets.py        — assets 表 CRUD
- system.py        — sys_status / trading_session / fee_config / reconcile_config + TradingClock
- quote_snapshots.py — quote_snapshots 表 CRUD
"""
from server.repo.orders import (
    ORDER_STATUS,
    TERMINAL_STATUSES,
    _get_active_trd_date,
    _infer_order_status,
    _status_msg,
    get_by_order_no,
    get_current_no,
    insert_cancel_row,
    insert_pending_order,
    is_cancellable,
    next_order_no,
    next_seq,
    reset_to,
)
from server.repo.system import TradingClock

infer_order_status = _infer_order_status  # public alias per design doc

__all__ = [
    "ORDER_STATUS",
    "TERMINAL_STATUSES",
    "TradingClock",
    "_get_active_trd_date",
    "_status_msg",
    "get_by_order_no",
    "get_current_no",
    "infer_order_status",
    "insert_cancel_row",
    "insert_pending_order",
    "is_cancellable",
    "next_order_no",
    "next_seq",
    "reset_to",
]
