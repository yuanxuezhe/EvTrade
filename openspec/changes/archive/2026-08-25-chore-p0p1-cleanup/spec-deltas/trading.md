# trading delta

## MODIFIED Requirements

### Requirement: 撤单端点单元测试覆盖

The system SHALL provide at least one happy-path unit test for `server/api/orders/cancel.py` exercising the full 5-step flow:
1. Insert `Orders` row with `status="50"` (已报) and a broker `order_id`
2. Mock `rpc_cancel_order` to return `code=0` (success)
3. Call `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD` via FastAPI TestClient
4. Assert: cancel row inserted with `status="54"`; original row's `cancelled_volume=volume`; cancel trade row inserted with `trade_type=1`

#### Scenario: 50→54 happy path

- **WHEN** test seeds an order with `status="50"` + `broker_order_id="BRK-001"` and calls cancel
- **THEN** response `code=0`, cancel-row `status="54"`, orig `cancelled_volume=volume`, one `Trades` row with `trade_type=1`

#### Scenario: 48 不可撤 (pre-check)

- **WHEN** test seeds an order with `status="48"` (未报) and calls cancel
- **THEN** response `code=1`, no cancel-row inserted, no RPC call made

### Requirement: place.py / cancel.py / repo/orders.py 死代码清理

`server/api/orders/place.py` SHALL NOT import `server.utils.time.format_ts` (function body never uses it). The helper `_compute_summary` in `server/services/t0/tasks.py` SHALL accept only `(task, **kwargs)` signature — the dual-signature `(db, task)` shim is removed because the API layer only calls `_compute_summary(t)`. The compat parameter `user_id_kw` in `create_task` / `list_tasks` SHALL be removed because the API layer already uses `user_id=`.

#### Scenario: 下单 import 收敛

- **WHEN** developer opens `server/api/orders/place.py`
- **THEN** the import block does NOT include `from server.utils.time import format_ts`

#### Scenario: t0 摘要单签名

- **WHEN** API calls `_compute_summary(task)`
- **THEN** the function accepts `task` as positional arg, returns dict with 6 keys (`task_net_volume`, `position_vol`, `realized_pnl`, `unrealized_pnl`, `trading_days`, `win_rate`)
- **AND** there is no path that accepts `(db, task)` two-positional signature

### Requirement: 服务端口、状态码、handler 逻辑零变更

This change SHALL NOT modify any of:
- 下单 / 撤单的 HTTP 端点签名（路由 / method / request model / response model）
- broker 状态码 48-57 的语义
- T0 配平算法 / 屏障（guards）/ 推送协议（push/dispatcher）
- 订单表 schema / 字段

Only dead code (unused imports, dead aliases, unused compat params, unused `_compute_summary` signature branch) is removed.