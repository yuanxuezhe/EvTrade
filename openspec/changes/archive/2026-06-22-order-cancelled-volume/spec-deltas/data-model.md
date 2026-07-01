# data-model delta — v8 cancelled_volume 字段

## MODIFIED Requirements

### §1 orders 表

#### Schema 变更
- 新增字段：`cancelled_volume`（`Integer`，nullable=False，default=0）

#### 新字段表

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `cancelled_volume` | Integer | NO | 0 | **累计撤单量**（v8 新增：broker ord_cfm 累加；用于推断已撤/部成部撤） |

#### 业务规则新增
- broker ord_cfm 推送 `cancelled_volume` / `cancel_volume` / `withdrawn_volume` 任一字段名时累加（兼容多版本 broker）
- 状态推断规则改（v8）：`cancelled_volume >= volume` → 53（已撤）；`cancelled_volume > 0 && traded_volume > 0` → 56（部成部撤）；`cancelled_volume > 0`（无成交）→ 53
- DB 迁移脚本：`migrations/migrate_cancelled_volume.py`（`ALTER TABLE orders ADD COLUMN cancelled_volume INTEGER NOT NULL DEFAULT 0`）

## Cross-References

- `trading/spec.md` REQ-TRADE-002 推断规则修订
- `push/spec.md` REQ-PUSH-005 v8 修订
- `frontend/spec.md` REQ-FE-006 inferOrderStatus 入参
- 实施 commit: `640419a`
