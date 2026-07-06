# trading delta — v13 cancel-row 增加 raw_id 字段（user_def 保持不变）

> change `layered-architecture-and-strategy-master` — 补集增量
>
> **本 delta 不修改 strategy_type 字段**（远程 `2026-07-05-strategy_trade` 已实现 `Strategy.type VARCHAR(16) DEFAULT 'general'`，值域 `{'general','t0'}`，详见 `openspec/specs/strategy/spec.md` REQ-STRAT-003）。本 delta 仅在 DELETE cancel-row 上增加结构化 `raw_id` 字段。
>
> **本 delta 不修改 user_def 语义**（远程 REQ-TRADE-011 确立 `user_def` 三种取值并存：str(strategy.id) / "T0" / "CANCEL:{no}"）。本 delta 仅**追加** raw_id 列作为 cancel-row 的结构化冗余字段。

## MODIFIED Requirements

### REQ-TRADE-003: 撤单（v13 改第 2 步 INSERT cancel-row 字段）

#### 5 步流程变更（第 2 步 INSERT cancel-row 字段追加 raw_id）

- **第 2 步 ★ MODIFIED：INSERT cancel-row 字段增加 raw_id**
  ```python
  cancel_row = Order(
      trd_date=orig.trd_date,
      order_no=next_order_no(db),
      user_def=f"CANCEL:{orig.order_no}",  # v9 约定，不动（远程 v9 audit 兼容）
      raw_id=orig.order_no,                 # ★ NEW 字段写入
      stock_code=orig.stock_code,
      order_type=orig.order_type,
      price_type=orig.price_type,
      price=orig.price,
      volume=0,
      order_flag=1,                         # v9 不变
      status="48",                          # broker UNREPORTED 本地 sentinel
      order_time=format_ts(tz='local'),
  )
  ```
- 其他 4 步不动（pre-checks / RPC / 分支 / WS broadcast）

#### WS broadcast payload 增加（v13 增字段）

- `order_update` payload 增加 `raw_id` 字段（值同 INSERT 时 = `orig.order_no`）
- 前端 `holdings.applyOrderPush` 透传此字段到 IDB
- `user_def` 仍透传（保持现有 WS payload 兼容）

#### Scenario: cancel.py 第 2 步 INSERT cancel-row 含 raw_id（v13 NEW）

- **WHEN** DELETE /api/orders/{order_no} 通过 pre-check
- **THEN** INSERT cancel-row 同时含 `user_def=f"CANCEL:{orig.order_no}"` + `raw_id=orig.order_no`（不是只含 user_def；不是用 raw_id 替代 user_def）

#### Scenario: cancel.py WS broadcast payload 含 raw_id（v13 NEW）

- **WHEN** DELETE /api/orders/{order_no} RPC 完成后 WS broadcast `order_update`
- **THEN** payload MUST 同时含 `user_def` + `raw_id`（不是只含 user_def）；前端 IDB 收到 raw_id 不报错（可选字段）

### REQ-TRADE-002: 下单（v13 不变更）

- 不动 `OrderOut` 既有字段
- 不动 `PlaceOrderRequest` 字段
- 不动 `Strategy.type` 字段（远程 REQ-STRAT-003 决定 `{'general','t0'}` 值域）
- 不动 `Order.user_def` 写入规则（远程 REQ-TRADE-011 决定 `str(strategy.id)`）

### REQ-TRADE-011: Order.user_def 关联约定（远程 owner，本 change 不动）

- 远程 `2026-07-05-strategy_trade` 确立的约定完全保持：
  - `Order.user_def = str(strategy.id)`（strategy 引擎下单）
  - `Order.user_def == "T0"`（历史手动 T0 委托）
  - `Order.user_def == f"CANCEL:{orig.order_no}"`（cancel-row）
  - `ix_orders_user_def` 索引（远程已加）
- 本 change 不修改 user_def 任何已有规则；仅在 cancel-row 上**追加** raw_id 作为结构化冗余

## ADDED Requirements

（本 change 不新增 trading 端点 — 远程 `2026-07-05-strategy_trade` 已实现 `GET /api/strategy/*` 全套 CRUD + 控制 + 审计）

### REQ-TRADE-012: cancel-row.raw_id 字段契约（v13 NEW）

- `Order.raw_id` 是 cancel-row 专属字段，普通 strategy 委托的 raw_id 永远为 NULL
- `Order.raw_id` 与 `Order.user_def`（`CANCEL:{no}` 格式）表达同一关联，但 raw_id 是结构化字段（String 8 位纯数字）
- 前端 / 后端 query 优先用 `raw_id` 做结构化 JOIN / 过滤；`user_def` 保留作 audit 兼容
- 反向查询：`SELECT orig_order.* FROM orders AS orig JOIN orders AS cancel ON cancel.raw_id = orig.order_no WHERE cancel.order_flag = 1` 可在 parent ↔ cancel 之间建立关系

#### Scenario: cancel-row 双重字段冗余校验（v13 NEW）

- **WHEN** 系统检测到 cancel-row `order_flag=1` 的行
- **THEN** MUST 同时满足 `user_def LIKE "CANCEL:%"` + `raw_id` 非 NULL + `raw_id = substr(user_def, 8)`（即 user_def 的 8 位数字 = raw_id）

## 不在本 delta 范围

- ❌ 改 `Strategy.type` 值域（远程 v9 锁定 `{'general','t0'}`）
- ❌ 改 `Order.user_def` 既有写入规则（远程 REQ-TRADE-011 owner）
- ❌ 改 `ix_orders_user_def` 索引（远程已加）
- ❌ 改 `_infer_order_status` / `TERMINAL_STATUSES`（v11 broker 字典对齐保持）
- ❌ 改 place.py 4 步流程（v11 broker 码业务写入点保持）
- ❌ 改前端 4 view（/trade /t0-trade /t-strategy /algo-strategy）的请求体字段 — **如需 4 view 显式打标可走 follow-up change**