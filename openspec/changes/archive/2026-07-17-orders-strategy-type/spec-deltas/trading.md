## ADDED Requirements

### REQ-TRADE-026: orders.strategy_type 业务契约（v66 NEW）

**业务定位**: 委托策略类型（强约束枚举 0/1），区分下单来源；T0Trade 缓存过滤的权威字段。

**字段语义**:
| 值 | 含义 | 下单入口 | user_def |
|---|---|---|---|
| 0 | 普通单 | `Trade.vue OrderForm` | `''` (空) |
| 1 | 快速做T | `T0Trade.vue` 智能做T | `'T0'` |

**API 契约**:
- `POST /api/orders/place` 入参 `strategy_type`: `Literal[0, 1]`, 默认 0
- 传 2 / -1 / 字符串 "1" → 422 ValidationError（Pydantic Literal 强约束）
- `OrderOut.strategy_type: int = 0` 输出 schema
- `_to_order_out(order)` helper 透传 strategy_type, 兜底 0（防 ORM 历史单 None）
- `_order_to_out_dict(order)` WS push 透传, 兜底 0

**撤单行继承**:
- 本地代理 cancel-row (order_flag=1) 不显式设 strategy_type
- SQLAlchemy ORM 复制时 strategy_type 自动 = 原委托 strategy_type
- 分类语义保留：原普通单撤单 → cancel-row strategy_type=0; 原做T单撤单 → cancel-row strategy_type=1

**数据迁移**:
- 旧 `user_def='T0'` 单（v66 之前下的）保持 strategy_type=0（DEFAULT 0 兜底）
- 不回填；前端如需识别旧 T0 单仍走 `user_def='T0'` 字符串过滤（向后兼容 REQ-TRADE-011）

#### Scenario: Trade.vue 下单 strategy_type=0

- **GIVEN** user 在 `/trade` 页面填单 → 点"确认买入/卖出"
- **WHEN** `orderStore.placeOrder(payload)` POST `/api/orders/place`
- **THEN** payload MUST 含 `strategy_type: 0`
- **AND** DB `orders.strategy_type = 0`
- **AND** WS push 含 `strategy_type: 0`
- **AND** Pinia `holdings.orders` 中该行 strategy_type = 0

#### Scenario: T0Trade.vue 下单 strategy_type=1

- **GIVEN** user 在 `/t0-trade` 页面 → 点"确认做T"
- **WHEN** `orderStore.placeOrder(payload)` POST `/api/orders/place`
- **THEN** payload MUST 含 `strategy_type: 1` AND `user_def: 'T0'`
- **AND** DB `orders.strategy_type = 1`
- **AND** WS push 含 `strategy_type: 1`
- **AND** Pinia `holdings.orders` 中该行 strategy_type = 1

#### Scenario: Pydantic Literal 拒绝非法值

- **WHEN** 客户端 POST `{strategy_type: 2}` OR `{strategy_type: -1}` OR `{strategy_type: "1"}`
- **THEN** 422 ValidationError
- **AND** DB 不会被写入（事务回滚）

#### Scenario: 撤单行 strategy_type 继承

- **GIVEN** 原 Order.strategy_type=1（做T单）
- **WHEN** DELETE `/api/orders/{order_no}` → 本地代理创建 cancel-row (order_flag=1)
- **THEN** cancel-row.strategy_type 自动 = 1（ORM 复制, 不显式设）
- **AND** 分类语义保留，filter `strategy_type=1` 同时包含原单 + cancel-row

#### Scenario: metaMerge 透传 strategy_type（防缓存丢字段）

- **GIVEN** `_upsertToHoldings(order)` 调用 `applyOrderPush`
- **WHEN** `metaMerge(row, ref)` 计算 merged
- **THEN** merged.strategy_type = row.strategy_type ?? ref.strategy_type ?? 0
- **AND** 历史 ref 中 strategy_type=undefined 时兜底 0
- **AND** T0Trade 委托明细 filter `o.strategy_type === 1` 立即生效（无需重刷 bootstrap）
