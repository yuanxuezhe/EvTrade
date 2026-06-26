"""
push_handlers.py — 推送落库 facade 兼容垫片（phase-2 拆分后）

实现已拆分到 server/services/push/ 子模块 + order_status.py。

保留本 facade 是为了不破坏既有 import 路径：
  from services.push_handlers import handle_push            ← rpc/transport.py
  from services.push_handlers import handle_push, _infer_order_status,
                                     TERMINAL_STATUSES, _status_msg  ← test_push_handlers.py

包含 4 个 handler 的注册表 HANDLERS + 统一入口 handle_push(db, func, row, ts)。
"""
import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from server.services.order_status import (
    ORDER_STATUS,
    TERMINAL_STATUSES,
    _get_active_trd_date,
    _infer_order_status,
    _status_msg,
)
from server.services.push.helpers import _float, _int, _str, _utcnow
from server.services.push.ord import handle_ord_cfm
from server.services.push.trd import handle_trd_cfm
from server.services.push.pos import handle_pos_cfm
from server.services.push.ast import handle_ast_cfm

log = logging.getLogger(__name__)

# 4 类 push → handler 路由表
HANDLERS = {
    "ord_cfm": handle_ord_cfm,
    "trd_cfm": handle_trd_cfm,
    "pos_cfm": handle_pos_cfm,
    "ast_cfm": handle_ast_cfm,
}


def handle_push(db: Session, func: str, row: Dict[str, Any], ts: str) -> None:
    """统一入口 — 同步签名（向后兼容 test_push_handlers.py 11 用例）。

    实际调用方在 rpc/transport.py 走 loop.run_in_executor 包装，不阻塞 event loop。
    """
    handler = HANDLERS.get(func)
    if not handler:
        log.warning("handle_push: unknown func=%r row=%r ts=%s", func, row, ts)
        return
    handler(db, row, ts)


__all__ = [
    # shared status
    "ORDER_STATUS", "TERMINAL_STATUSES",
    "_status_msg", "_infer_order_status", "_get_active_trd_date",
    # helpers
    "_str", "_float", "_int", "_utcnow",
    # handlers
    "handle_ord_cfm", "handle_trd_cfm", "handle_pos_cfm", "handle_ast_cfm",
    # dispatch
    "HANDLERS", "handle_push",
]
