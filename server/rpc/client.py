"""
client.py — RPC 客户端 facade 兼容垫片（phase-2 拆分 + simplify-rpc-transport-thin）

实现已拆分到 6 个单一职责子模块：
- transport.py — RPClient 传输骨架（connect / call / listeners / 单例 + 2 wire utility）
- parsers_common.py (~109) — 通用响应解析工具（_select_rs / _parse_code_msg / _iter_rows / _to_* / _empty）
- parsers_business.py (~152) — 业务特定解析器（_parse_asset / _parse_orders / _parse_trades / _parse_positions / _parse_order_ack）
- parsers_push.py — push 行提取（_iter_push_rows，从 transport 迁出）
- handlers.py (~100) — 业务 RPC 调用入口（qry_* / ord_stk / cancel_order）
- server/services/push/dispatcher.py — push 业务编排器（编排层）
    routes.py / run_handlers.py / log_helpers.py — 路由表 / 落库 helper / 日志 helper

保留本 facade 是为了不破坏既有 import 路径：
  from rpc.client import ...            ← test_rpc.py / test_rpc_link.py
  from server.rpc.client import ...     ← api/orders.py / main.py / services/reconcile.py

测试 / 业务代码用到的所有符号（RABBITMQ_URL / RPClient / get_rpc_client /
close_rpc_client / ord_stk / cancel_order / qry_* / _PUSH_CHANNEL / EXCHANGE_NAME
/ QUEUE_*）都在此 re-export。
"""
from server.rpc.transport import (
    MAX_PENDING,
    RABBITMQ_URL,
    EXCHANGE_NAME,
    QUEUE_REQ,
    QUEUE_REPLY,
    QUEUE_PUSH,
    RPClient,
    _clean_id,
    _wire_dump,
    close_rpc_client,
    get_rpc_client,
)
from server.rpc.parsers_push import _iter_push_rows
from server.rpc.parsers_common import (
    _empty,
    _iter_rows,
    _parse_code_msg,
    _select_rs,
    _to_float,
    _to_int,
)
from server.rpc.parsers_business import (
    _parse_asset,
    _parse_order_ack,
    _parse_orders,
    _parse_positions,
    _parse_trades,
)
from server.services.push.dispatcher import PushDispatcher
from server.services.push.routes import _PUSH_CHANNEL
from server.services.push.run_handlers import (
    _resolve_active_trd_date_safe,
    _run_handle_push,
)
from server.rpc.handlers import (
    cancel_order,
    ord_stk,
    qry_asset,
    qry_orders,
    qry_positions,
    qry_trades,
)

__all__ = [
    # transport
    "MAX_PENDING",
    "RABBITMQ_URL", "EXCHANGE_NAME",
    "QUEUE_REQ", "QUEUE_REPLY", "QUEUE_PUSH",
    "RPClient",
    "_clean_id", "_wire_dump",
    "get_rpc_client", "close_rpc_client",
    # parsers push
    "_iter_push_rows",
    # parsers common
    "_select_rs", "_parse_code_msg", "_iter_rows",
    "_to_float", "_to_int", "_empty",
    # parsers business
    "_parse_asset", "_parse_orders", "_parse_trades",
    "_parse_positions", "_parse_order_ack",
    # push dispatcher (re-export from services/push/{routes,run_handlers}.py)
    "_PUSH_CHANNEL", "_run_handle_push", "_resolve_active_trd_date_safe",
    # handlers
    "qry_asset", "qry_orders", "qry_trades", "qry_positions",
    "ord_stk", "cancel_order",
]