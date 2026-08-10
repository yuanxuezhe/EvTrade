# spec-delta: trading（现有 spec 增量）

## MODIFIED Requirements

### REQ-TRADE-011: Order.user_def 关联约定 — 去掉策略表 JOIN

> **变更说明（2026-08-10）**：commit `aa70dae` 删除 strategy 表（含 `type='t0'` 策略）。`resolve_t0_user_defs`（`server/services/t0/aggregators.py`）v124 起只返回 `{'T0'}`，不再查询策略表。`/api/strategy/t0_endpoints.py` 已删（T0 交易走 `t0_tasks` 体系）。

更新内容：

- ~~"`resolve_t0_user_defs` 返 Set[str]，含字面量 T0 + 所有 type='t0' strategy.id 的字符串化"~~ → v124 起 `"T0"` → `{'T0'}` 单值
- ~~"strategy 引擎下单时写 `user_def = str(strategy.id)`"~~ → 策略表已删，不再产生新策略单；历史值仍参与查询（文档保留）
- Scenario "strategy 委托 user_def=str(id)" / "T0 端点含 t0 strategy 单子" → 重写为"人工 T0 委托归属"（策略表已删）

## 保留（未变）

- `ix_orders_user_def` 索引约定、`apply_user_def_filter` 向后兼容、REQ-TRADE-002 remark 透传
