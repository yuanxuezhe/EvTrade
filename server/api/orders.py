"""
orders.py — 委托 API facade 兼容垫片（phase-2 拆分后）

实现已拆分到 4 个单一职责子模块：
- _order_schemas.py — Pydantic schemas + _to_order_out helper
- order_place.py    — POST /place 下单端点（register_place）
- order_cancel.py   — DELETE /{order_no} 撤单端点（register_cancel）
- order_query.py    — GET / 和 GET /history 查询端点（register_query）

保留本 facade 是为了不破坏既有 import 路径：
  from server.api.orders import router            ← main.py: app.include_router
  from server.api.orders import ord_stk            ← test_orders_api.py: monkeypatch
  from server.api.orders import rpc_cancel_order   ← test_orders_api.py: monkeypatch
  from server.api.orders import ws_manager         ← test_orders_api.py: monkeypatch

**关键**：test_orders_api.py 走 `monkeypatch.setattr("api.orders.<name>", mock)`，
因此 patched symbol 必须在 api.orders 顶层 import，order_place / order_cancel
端点函数体内通过 `from server.api.orders import <name>` 拿被 patch 后的版本。
"""
import logging

from fastapi import APIRouter

# Top-level imports 是 test_orders_api.py monkeypatch 目标，必须保留
from server.rpc.client import ord_stk, cancel_order as rpc_cancel_order
from server.ws.manager import ws_manager

# 端点注册（register_* 把 @router.<method> 挂到 router）
from server.api.order_place import register_place
from server.api.order_cancel import register_cancel
from server.api.order_query import register_query

# Schema re-export（5 个 Pydantic + 1 个 helper）
from server.api._order_schemas import (
    CancelResponse,
    ListOrdersResponse,
    OrderOut,
    PlaceOrderRequest,
    PlaceOrderResponse,
    _to_order_out,
)

log = logging.getLogger(__name__)

router = APIRouter()
register_place(router)
register_cancel(router)
register_query(router)

__all__ = [
    "router",
    # patched symbols (top-level imports for monkeypatch)
    "ord_stk", "rpc_cancel_order", "ws_manager",
    # schemas
    "PlaceOrderRequest", "OrderOut", "PlaceOrderResponse",
    "ListOrdersResponse", "CancelResponse",
    "_to_order_out",
]
