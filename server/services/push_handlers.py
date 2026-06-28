"""兼容垫片 — push_handlers 实现已下沉到 server.services.push.handlers

保留本文件是为了不破坏既有 import 路径：
  from services.push_handlers import handle_push                    ← rpc/transport.py
  from services.push_handlers import handle_push, _infer_order_status,
                                     TERMINAL_STATUSES, _status_msg  ← test_push_handlers.py

新代码请直接 import：
  from server.services.push.handlers import handle_push, HANDLERS, ...
"""
from server.services.push.handlers import (  # noqa: F401
    # shared status
    ORDER_STATUS,
    TERMINAL_STATUSES,
    _get_active_trd_date,
    _infer_order_status,
    _status_msg,
    # helpers
    _str,
    _float,
    _int,
    _utcnow,
    # handlers
    handle_ord_cfm,
    handle_trd_cfm,
    handle_pos_cfm,
    handle_ast_cfm,
    # dispatch
    HANDLERS,
    handle_push,
)