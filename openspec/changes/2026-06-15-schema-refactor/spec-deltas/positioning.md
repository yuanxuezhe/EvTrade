# positioning spec delta

## REQ-POS-001（改写）

**原**：Position 字段 `stock_code, stock_name, initial_position, today_buy, today_sell, available, total, cost`
**新**：Position 字段 `stock_code, stock_name, last_vol, today_buy, today_sell, avl_vol, vol, cost_price`

| 旧字段 | 新字段 | 备注 |
|---|---|---|
| `initial_position` | `last_vol` | 期初持仓（柜台术语） |
| `available` | `avl_vol` | 可用持仓 |
| `total` | `vol` | 总持仓 |
| `cost` | `cost_price` | 成本价 |

- 删除 `id` / `TRD_DATE` 字段
- 主键改为 `stock_code`（单股唯一）
- `market_value` 计算代理从 `cost * total` 改为 `cost_price * vol`
- `do_reconcile._apply_broker_data` 改为先 `db.query(Position).delete()` 再 `db.add_all(...)`，替代原"按 (TRD_DATE, stock_code) UPSERT"
- `handle_pos_cfm` 改为按 `stock_code` PK 直接 UPSERT，无 TRD_DATE 过滤
