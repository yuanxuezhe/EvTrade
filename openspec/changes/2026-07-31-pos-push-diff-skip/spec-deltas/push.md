# push spec delta — pos_push diff skip

## REQ-PUSH-034: pos_push 无变化时跳过落库与广播

broker 每次推送 `pos_push` 时，`handle_pos_push` MUST 在写库前对 4 个持仓业务字段做 diff 判断；与 DB 现有行完全相等时 MUST 返回 `None`，由 dispatcher 跳过 WS 广播。

### Diff 字段集合

`{last_vol, vol, avl_vol, cost_price}` — 与 `REQ-PUSH-031`（trd_cfm 增量更新作用域）保持一致。

`stock_name` / `synced_at` / `synced_from` **不参与 diff 判断**：新 row 仍按现有路径 add_one + 标记 `synced_from='pos_push'` + 刷 `synced_at`；已有 row 在 diff 通过时直接返回 None（**不刷 synced_at**，避免心跳污染）。

### 实现位置

`server/services/push/pos.py::handle_pos_push` 入口加本地辅助函数 `_fields_unchanged(existing_pos, incoming) -> bool`：

- 输入：`existing_pos`（ORM Row 或 None）、`incoming`（dict，含 last_vol/vol/avl_vol/cost_price）
- 输出：`True` 当且仅当 4 个字段全部相等
- 新建行（`existing_pos is None`）→ `False`（继续走 add_one 路径）

### dispatcher 契约（不变）

`_broadcast_generic` 已处理 `handler_result is None → return`（见 `REQ-PUSH-007` v78 修订）。pos_push 走 `_broadcast_generic` 路径，无需 dispatcher 改动。

### 不在范围内

- ❌ 不影响 `handle_ord_cfm` / `handle_trd_cfm`（它们有自身的 status / vol 增量逻辑）
- ❌ 不影响 `_PUSH_CHANNEL` 路由表（pos_push → position_update 不变）
- ❌ 不影响前端 `_onPosPush`（payload 形态不变；只是"同值不会到达"）

### Scenario: pos_push 字段无变化 → 跳过落库与广播

- **WHEN** broker 推 `pos_push` 行 `{stock_code:"X", last_vol:100, vol:100, avl_vol:100, cost_price:12.5}`
- **AND** `positions` 表已有行 `{stock_code:"X", last_vol:100, vol:100, avl_vol:100, cost_price:12.5}`（4 字段全等）
- **THEN** `handle_pos_push` MUST 返回 `None`
- **AND** `positions` 表行**不更新**（synced_at / synced_from 也不刷）
- **AND** dispatcher 不调用 `ws_manager.broadcast('position_update', ...)`
- **AND** 前端 `_onPosPush` 不被触发

### Scenario: pos_push 字段变化 → 走 UPDATE + 广播

- **WHEN** broker 推 `{stock_code:"X", last_vol:100, vol:200, avl_vol:150, cost_price:13.0}`
- **AND** `positions` 表已有行 `{last_vol:100, vol:100, avl_vol:100, cost_price:12.5}`（cost_price 或 vol 变化）
- **THEN** `Positions.update_one` 写入新值 + `synced_at` + `synced_from='pos_push'`
- **AND** 返回 `{position: ...}`
- **AND** dispatcher 广播 `position_update` 给前端

### Scenario: pos_push 新建行 → 不走 diff

- **WHEN** broker 推 `pos_push` 行 `{stock_code:"X", last_vol:100, vol:100, avl_vol:100, cost_price:12.5}`
- **AND** `positions` 表**无** stock_code="X" 行
- **THEN** `Positions.add_one` 创建新行（现有行为不变）
- **AND** 返回 `{position: ...}` 给前端