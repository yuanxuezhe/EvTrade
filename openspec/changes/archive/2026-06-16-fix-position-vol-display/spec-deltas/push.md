# push spec delta — pos_cfm 字段映射

**合并到**：`openspec/specs/push/spec.md`

## pos_cfm 字段映射增量

`handle_pos_cfm` 字段映射：
- `row.volume` → `pos.vol`（缺字段或 0 时兜底为 `pos.avl_vol`）
- `row.available` → `pos.avl_vol`
- `row.cost_price` → `pos.cost_price`
- **不写** `last_vol` / `today_buy` / `today_sell`（对账写）
- **不写** `market_value`（前端实时算）
