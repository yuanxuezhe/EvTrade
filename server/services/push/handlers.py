"""
push/handlers.py — 2 类 broker push 路由表 + 统一入口 handle_push

change consolidate-position-data-flow: pos_cfm / ast_cfm handler 已删除
(xtquant broker 协议不发送这两个事件)。仅剩 ord_cfm / trd_cfm 两个 handler。

调用方：
  - server/services/push/dispatcher.py  _run_handle_push
  - tests/server/services/push/test_handlers.py  handle_push + _infer_order_status
  - server/test_push_handlers.py  (legacy, 待迁移)
  - server/test_push_async.py  handle_push
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from server.repo.orders import (
    ORDER_STATUS,
    TERMINAL_STATUSES,
    _get_active_trd_date,
    _infer_order_status,
    _status_msg,
)
from server.services.push.helpers import _float, _int, _str
from server.utils.time import _utcnow  # bugfix: was wrongly imported from helpers (never existed there)
from server.services.push.ord import handle_ord_cfm
from server.services.push.trd import handle_trd_cfm
from server.services.push.pos import handle_pos_push   # v118: pos_push 推送处理

log = logging.getLogger(__name__)

# 2 类 push → handler 路由表 (change consolidate-position-data-flow)
# v118: 新增 pos_push 路由 (持仓变化推送, broker 直接刷新本地 + 推前端)
HANDLERS = {
    "ord_cfm": handle_ord_cfm,
    "trd_cfm": handle_trd_cfm,
    "pos_push": handle_pos_push,
}


def handle_push(db: Session, func: str, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """统一入口 — 同步签名（向后兼容 test_push_handlers.py）。

    返回 handler 的结果（OrderOut/TradeOut 兼容 dict），供 WS 推送重组包。
    实际调用方在 rpc/transport.py 走 loop.run_in_executor 包装，不阻塞 event loop。
    """
    handler = HANDLERS.get(func)
    if not handler:
        log.warning("handle_push: unknown func=%r row=%r ts=%s", func, row, ts)
        return None
    return handler(db, row, ts)


__all__ = [
    # shared status
    "ORDER_STATUS", "TERMINAL_STATUSES",
    "_status_msg", "_infer_order_status", "_get_active_trd_date",
    # helpers
    "_str", "_float", "_int", "_utcnow",
    # handlers
    "handle_ord_cfm", "handle_trd_cfm",
    # dispatch
    "HANDLERS", "handle_push",
]
