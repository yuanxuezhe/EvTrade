# 2026-07-31-pos-push-diff-skip — pos_push 无变化时跳过落库与广播

## Why

`runtime_trdapi_rel.py::position_callback` 在 broker 每次推送 pos_push 时都会触发 `server/services/push/pos.py::handle_pos_push`。当前实现：
- **无条件** 走 `Positions.add_one` / `Positions.update_one`（写 DB）
- **无条件** 返回 `{position: ...}` 给 dispatcher `_broadcast_generic`（推 WS）

broker 重连、心跳、或 xtquant 自身去重失败时会出现**重复同值推送**，造成：
1. 每次都产生一次 `positions` 表 UPDATE（含 `synced_at` 时间戳刷写，事后看不出真实变化）
2. 每次都广播 `position_update` 给前端，前端 `_onPosPush` → `holdings.applyPositionUpdate` 整条 ref 替换（Vue ref reactivity 触发下游 computed 重算）
3. 前端写 log 无意义 + UI 不必要的抖动风险

用户原话 (2026-07-31)："给后端，请后端按推送刷新数据，若数据存在变化，则更新持仓表并推送前端刷新持仓缓存，没变化则忽略。"

## What Changes

`handle_pos_push` 入口加 diff 检查：4 个持仓业务字段（`last_vol`/`vol`/`avl_vol`/`cost_price`）若与 DB 现有行完全相等，直接返回 `None`，dispatcher 检测到 `handler_result is None` 时已经**跳过广播**（现有契约 REQ-PUSH-007 兼容）。

`stock_name` / `synced_at` / `synced_from` 不参与 diff 判断（每次推送会刷 `synced_at` 是正常的"心跳确认"信号，但不应触发 DB UPDATE 与广播）。

### 关键设计

- **diff 字段集合** = `{last_vol, vol, avl_vol, cost_price}`（与 REQ-PUSH-031 增量更新作用域一致）
- **新创建行不参与 diff**（pos 不存在时按现有逻辑 add_one 后返回）
- **不引入新模块**：diff 工具函数 `_fields_unchanged(existing_pos, incoming) -> bool` 收纳在 `pos.py` 内（helpers.py 不外置，避免为单点改动过度抽象）
- **dispatcher 无需改动**：`_broadcast_generic` 已处理 `handler_result is None → return`（REQ-PUSH-007 v78）

### 不在范围内

- ❌ 不动 `handle_ord_cfm` / `handle_trd_cfm`（这两条已有自身的 vol/cost_price 增量逻辑）
- ❌ 不动前端 `_onPosPush`（payload 形态不变）
- ❌ 不动 `do_reconcile`（全天覆盖仍照旧）
- ❌ 不动 `_PUSH_CHANNEL` 路由表（pos_push → position_update 不变）

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 业务 | `server/services/push/pos.py` | `handle_pos_push` 入口加 `_fields_unchanged` 守门；无变化 → return None |
| 测试 | `server/tests/push/test_pos_push_diff.py` | **新增**：3 个用例（无变化返回 None / 字段变化走 UPDATE / 新建行不走 diff） |
| 知识库 | `openspec/specs/push/spec.md` | 新增 REQ-PUSH-034：pos_push 无变化时跳过落库与广播 |
| 知识库 | `openspec/specs/positioning/spec.md` | REQ-POS-003 数据来源段加注 pos_push diff 行为 |

## 落地约束

- ✅ 与 OpenSpec 工作流一致：先建 change proposal → 同步 spec → 再写代码 → 归档
- ✅ diff 字段集合对齐 REQ-PUSH-031（vol / avl_vol / cost_price / last_vol）
- ✅ 不改 `helper.py`（避免过早抽象）
- ✅ 不自动 push（用户硬性偏好）
- ✅ 浏览器/ws 实测：连 broker → 推送重复同值 → 前端 `_onPosPush` 不被二次触发（devtools ws frame 不再新增）

## 关联

- 上游：v118 broker 引入 `pos_push`（commit `df385b4` / `b194441` / `9243b75` / `7868a40`）
- 现有契约：`push/spec.md` REQ-PUSH-031（trd_cfm vol 增量）/ REQ-PUSH-007 v78（handler_result is None 跳过广播）
- 知识库：`openspec/specs/push/spec.md` §REQ-PUSH-034（新增段）/ `positioning/spec.md` §REQ-POS-003（修订段）