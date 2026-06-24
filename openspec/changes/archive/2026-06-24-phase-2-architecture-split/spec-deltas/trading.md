# REQ-TRADE-008: orders.py phase-2 拆分

## ADDED Requirements

### REQ-TRADE-008: orders API 模块边界（phase-2 facade）

- **位置**：
  - `server/api/orders.py` — facade router（58 行,装配 4 子路由）
  - `server/api/_order_schemas.py` — Pydantic schemas（OrderOut / CancelResponse / PlaceRequest）
  - `server/api/order_place.py` — `register_place(router)` 下单端点
  - `server/api/order_cancel.py` — `register_cancel(router)` 撤单端点（5 步流程）
  - `server/api/order_query.py` — `register_query(router)` 委托/成交查询
- **late import 模式**：子模块内部 `from server.api.orders import ord_stk, rpc_cancel_order, ws_manager`（monkeypatch 兼容）
- **facade 兜底**：`from server.api.orders import router` 仍可解析；`app.include_router(orders.router, ...)` 0 改动
- **共享符号 re-export**：`OrderOut` / `CancelResponse` / `_to_order_out` 必须在 `orders.py` 顶部 re-export（test_orders_api.py 依赖）
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/`

#### Scenario

Given `server/test_orders_api.py` imports `from server.api.orders import OrderOut, CancelResponse, _to_order_out`
When `orders.py` 改为 facade
Then 3 个共享符号在 `orders.py` 顶部 re-export → 796 行测试文件可继续 import
