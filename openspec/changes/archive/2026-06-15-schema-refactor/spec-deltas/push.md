# push spec delta

## ord_cfm 消息结构 — 改写

**删除**：`order_remark`（与 broker 字段重名，本地表不再存）

**新增 / 调整**：
- `remark` 字段保留，但语义改为"柜台透传字段 = 本地 order_no"，用于 `handle_ord_cfm` 的兜底匹配
- `status_msg` 保留（废单 / 撤单原因文本）

## ord_cfm 匹配规则 — 新增

```
handle_ord_cfm(row, ts):
  1. broker_order_id = row.order_id
  2. broker_remark   = row.remark   # = 本地 order_no

  if broker_order_id:
      order = db.query(Order).filter_by(order_id=broker_order_id).first()
  if not order and broker_remark:
      order = db.query(Order).filter_by(order_no=broker_remark, trd_date=active_trd_date).first()
  if not order:
      log WARN  # ghost push, no match
      return
  # 命中 → 更新 status / traded_volume / traded_amount / avg_price / status_msg
```

## handle_ord_cfm 行为约束

- 不创建新 Order（仅做"已存在 + 状态更新"）
- 不写本地 `order_no`（已存在）
- 复合主键 `(trd_date, order_id)` 由 `order_id` 列单点定位；`trd_date` 用 active 交易日（resolve_default_trd_date 兜底）

## trd_cfm / pos_cfm / ast_cfm 字段对齐

- `trd_cfm`：用 `(trd_date, trade_id)` 复合主键
- `pos_cfm`：用 `stock_code` PK（无 TRD_DATE）
- `ast_cfm`：无主键，删 `db.query(Asset).first()` 后整行覆盖
