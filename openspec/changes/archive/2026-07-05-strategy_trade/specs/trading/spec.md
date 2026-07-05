## ADDED Requirements

### Requirement: Strategy 引擎下单 user_def 关联约定（REQ-TRADE-011）

策略引擎下所有订单 MUST `Order.user_def = str(strategy.id)`（裸 strategy_id 作 key，无 'STRATEGY:' 前缀），与现有 `user_def='T0'` / `user_def='CANCEL:{no}'` 共用同一字段，靠 JOIN `strategy` 表区分语义。Order 表 MUST 加 `Index("ix_orders_user_def", "user_def")` 支撑关联查询。

完整契约（含与 T0 / CANCEL 共存语义、索引、查询范式）见 `specs/strategy/spec.md` §REQ-STRAT-010。本节仅在 trading 域文档化约定。

#### Scenario: 策略单 user_def 写入

- **WHEN** 策略引擎调 `ord_stk(...)` 提交买单，strategy.id=5
- **THEN** Order.user_def MUST = `'5'`（`str(5)`），无前缀

#### Scenario: 三类 user_def 共存

- **WHEN** 同 trading_day 内存在：
  - 手动 T0 单 user_def='T0'
  - 撤单 audit row user_def='CANCEL:10000023'
  - 策略单 user_def='5'
- **THEN** 3 类 Order 在数据库共存
- **AND** `WHERE user_def = 'T0'` 仅命中 T0 单
- **AND** `WHERE user_def = '5'` 仅命中策略 5 单
- **AND** `WHERE user_def LIKE 'CANCEL:%'` 仅命中撤单审计

#### Scenario: 策略单被手动撤单

- **WHEN** 策略单（user_def='5'）被 trader 调 DELETE /api/orders/{order_no}
- **THEN** cancel-row 写入 user_def='CANCEL:{orig_order_no}'（沿用 REQ-TRADE-003 v9 约定），**不继承**原 user_def='5'
- **AND** 策略引擎下次评估按 broker 推送的 cancel-row status=54 重算 position_vol

#### Scenario: 索引性能

- **WHEN** 单策略订单数 > 10000 行
- **THEN** `WHERE user_def = '<id>'` 查询 MUST < 50ms（依赖 `ix_orders_user_def` 索引；服务端 ORDER BY 仍走 `ix_orders_trd_status`）

#### Scenario: audit JOIN 反查策略名 + type

- **WHEN** 前端 audit 页要展示某 Order 的策略名 + 类型
- **THEN** SQL: `SELECT o.*, s.name, s.type FROM orders o LEFT JOIN strategy s ON o.user_def = CAST(s.id AS TEXT) WHERE o.order_no = '<no>'`
- **AND** 若 user_def 不在 strategy.id 集合（普通单 / 撤单 / 手动 T0），LEFT JOIN 返回 NULL 策略名 + NULL type，UI 显示「非策略单」
- **AND** 若匹配到 strategy，UI 显示策略名 + 「T0 策略」/「普通策略」type badge

#### Scenario: T0 端点 JOIN strategy 迁移

- **WHEN** Strategy(id=5, type='t0') 当天下单 user_def='5'（非 'T0'）
- **AND** 同时手动 T0Trade.vue 下单 user_def='T0'
- **THEN** `GET /api/orders/t0-stats/{stock_code}?t0_only=true` MUST 含两类单（union `user_def='T0' OR (user_def IN strategy_ids WHERE type='t0')`）
- **AND** 响应 schema 与改造前一致（零 BREAKING）

完整 T0 端点集成合约见 `specs/strategy/spec.md` §REQ-STRAT-014。