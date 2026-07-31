# positioning spec delta — pos_push diff skip

## REQ-POS-003 修订

在 `data source` 段的 `pos_push` push 路径描述里加注：

> - **pos_push** 路径（broker 主动 `position_callback` → `pos_push`，v118 引入）：
>   - handler 入口对 4 个业务字段 `{last_vol, vol, avl_vol, cost_price}` 做 diff
>   - 与 DB 现有行全等 → 返回 `None`，dispatcher 跳过 WS 广播
>   - 与 DB 现有行不等 → 走 `Positions.update_one` + broadcast `position_update`
>   - 新建行 → 走 `Positions.add_one` + broadcast（不参与 diff）
>   - `synced_from='pos_push'` 标记来源
> - 详细契约见 `push/spec.md` REQ-PUSH-034