# data-model delta — v7 schema 修订

## MODIFIED Requirements

### §1 orders 表

#### Schema 变更
- 删除字段：`client_order_id`（`String(64)`，nullable=False）
- 新增字段：`user_def`（`String(255)`，nullable=False，default=""）
- 删除约束：`uq_orders_client_trd(client_order_id, trd_date)`
- 删除约束：`uq_orders_broker_id(order_id, trd_date)`（order_id 在下单时为空，UNIQUE 不可靠）

#### 新字段表

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `user_def` | String(255) | NO | "" | 外部自定义信息透传（前端幂等号 / 备注等），不做 DB 约束 |

#### 业务规则新增
- `user_def` 是纯透传字段，可写可读，不参与任何 DB 唯一性 / 幂等
- 幂等改由 `order_no` 单调递增保证（同 ord_stk RPC 第二次调用方会被 broker 拒绝）

### §2 trades 表

#### Schema 变更
- 删除字段：`order_id`（`String(64)`，nullable=False）
- 新增字段：`order_no`（`String(8)`，nullable=False，**入 PK**）
- PK 改为：`(trd_date, order_no, trade_id)`
- Index 重命名：`ix_trades_order(order_id)` → `ix_trades_order_no(order_no)`

#### 业务规则新增
- `order_no` 是稳定关联键（trd_cfm 早于 ord_cfm 到达时也能定位）
- trd_cfm 落 Trade 时若 `order_no` 解析失败 → 打 warning + 跳过该条（**不写孤儿 Trade**）

## Cross-References

- `trading/spec.md` REQ-TRADE-002（v7 schema 调整说明）
- `push/spec.md` REQ-PUSH-001（v7 handle_trd_cfm 落库调整）
