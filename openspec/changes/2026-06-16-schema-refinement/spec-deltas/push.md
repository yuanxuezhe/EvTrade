# push delta — v7 schema 修订

## MODIFIED Requirements

### REQ-PUSH-001: handle_trd_cfm 落库调整（v7）

**Before (v6)**:
- `Trade.order_id` 字段从 `remark` 解析得到 → 写入 Trade 表
- Trade PK = `(trd_date, trade_id)`，order_id 仅作为普通字段

**After (v7)**:
- 解析 `remark` → `order_no`（保持不变）
- 落 Trade 时**不再写** `order_id`，**写** `order_no`（PK 第二段）
- Trade PK = `(trd_date, order_no, trade_id)`（order_no 入 PK）
- 若 `remark` 解析失败（order_no 缺失）→ 打 warning 日志 + 跳过该条成交（**不写孤儿 Trade**）

#### 落库字段映射变更

| 字段来源 | Before | After |
|---|---|---|
| `row.trade_id` | Trade.trade_id | Trade.trade_id |
| `row.remark` 解析 → order_no | Trade.order_id ❌ | **Trade.order_no ✅**（入 PK） |
| `row.stock_code` | Trade.stock_code | Trade.stock_code |
| `row.price` | Trade.price | Trade.price |
| `row.volume` | Trade.volume | Trade.volume |
| `row.trade_time` | Trade.trade_time | Trade.trade_time |

#### 异常处理

- `remark` 解析失败 → logger.warning(...) + 不插入（防止孤儿 Trade）
- `trade_id` 缺失 → fallback `f"{order_no}-{trade_time}"`（v7 改：原 `f"{order_id}-{trade_time}"`）
- `trd_date` 缺失 → 用 `_get_active_trd_date(db)`

## Cross-References

- `data-model/spec.md` §2 trades 表
- `trading/spec.md` REQ-TRADE-002（v7 schema 调整说明）
