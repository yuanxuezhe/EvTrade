## ADDED Requirements

### Requirement: 14. `orders.strategy_type` 列新增（v66 新增）

**业务定位**：委托策略类型（强约束枚举，区分下单来源）。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_type` | TINYINT | NO | 0 | 0=普通单(Trade.vue OrderForm 下单) 1=快速做T(T0Trade.vue 智能做T下单) |

**迁移策略**:
- `ALTER TABLE orders ADD COLUMN strategy_type TINYINT NOT NULL DEFAULT 0` 幂等
- `CREATE INDEX ix_orders_strategy_type ON orders(strategy_type)` 幂等（MySQL 8 不支持 IF NOT EXISTS, 通过 INFORMATION_SCHEMA.STATISTICS 探测跳过）
- **不回填**: 历史 user_def='T0' 单保持 `strategy_type = 0`, 继续走 user_def 字符串聚合路径（向后兼容）

**与 user_def 关系**:
- Trade.vue OrderForm 下单（普通单）: `user_def = ''` AND `strategy_type = 0`
- T0Trade.vue 智能做T下单（v66 NEW）: `user_def = 'T0'` AND `strategy_type = 1`
- 历史 T0 单（无显式 strategy_type）: `user_def = 'T0'` AND `strategy_type = 0`（DEFAULT 兜底）

**与 task_id 关系**:
- task 下单（v18 行为）: `user_def = 'T0'` AND `task_id = <id>` AND `strategy_type = 1`
- 无 task 的 T0 单: `user_def = 'T0'` AND `task_id = NULL` AND `strategy_type = 1`
- 普通单: `user_def = ''` AND `task_id = NULL` AND `strategy_type = 0`

#### Scenario: migration 幂等检测列存在

- **WHEN** migration 跑
- **THEN** 先查 `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='orders' AND COLUMN_NAME='strategy_type'`
- **AND** 已存在则跳过 ALTER；不存在则 ADD COLUMN
- **AND** 通过 inspect(engine).get_columns('orders') 探测（业务库 + 业务账号验证）

#### Scenario: migration 幂等检测索引存在

- **WHEN** 创建索引
- **THEN** 先查 `INFORMATION_SCHEMA.STATISTICS WHERE TABLE_NAME='orders' AND INDEX_NAME='ix_orders_strategy_type'`
- **AND** 已存在则跳过 CREATE INDEX；不存在则 CREATE INDEX

#### Scenario: 撤单行 strategy_type 继承原单

- **WHEN** 撤单本地代理创建 cancel-row (order_flag=1)
- **THEN** cancel-row 的 strategy_type 字段自动 = 原委托 strategy_type（SQLAlchemy ORM 复制，不显式设 strategy_type）
- **AND** 分类语义保留：原普通单撤单 → strategy_type=0 cancel-row；原做T单撤单 → strategy_type=1 cancel-row

#### Scenario: Pydantic Literal 强约束

- **WHEN** 客户端 POST `/api/orders/place` payload
- **THEN** `PlaceOrderRequest.strategy_type` 必须 = 0 或 1
- **AND** 传 2 / -1 / "1"（字符串）→ 422 ValidationError
- **AND** 不传 → 默认 0（与 ORM DEFAULT 0 对齐）
