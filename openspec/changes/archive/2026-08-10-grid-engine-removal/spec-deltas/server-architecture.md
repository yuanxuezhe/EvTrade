# spec-delta: server-architecture（现有 spec 增量）

## MODIFIED Requirements

### server/services/strategy/ 子模块引用 — 网格引擎已删

> **变更说明（2026-08-10）**：commit `aa70dae` 删除了 `server/services/strategy/` 中网格引擎子模块（engine / repository / grid / regime / audit / flags / indicators / t0），仅保留 `signal_consumer`（MQ→下单）+ 重写后的 `quote_consumer`（纯行情快照 + `quote_update` 广播）。`server/api/strategy.py` / `api/strategy/` 目录已删。

修正以下引用：

- ~~"包含远程 strategy：server/services/strategy/（models / repository / indicators / flags / regime / grid / engine / quote_consumer / audit 等）"~~ → `server/services/strategy/` 现仅含 `signal_consumer` + `quote_consumer`
- ~~"包含远程 strategy：server/api/strategy.py（CRUD + 控制 + 审计查询 REST 端点）"~~ → `server/api/strategy/` 已删除；`server/api/script_strategy/` 现行（14 端点，v90）
- ~~"`server/api/strategy.py` — 远程 strategy_trade 顶层 re-export 允许跨层"~~ → 删除
- ~~"远程豁免：server/services/strategy/ 多个子模块（repository / indicators / flags / regime / grid / engine 等）允许 deep import"~~ → 已删子模块豁免不再需要；`signal_consumer` / `quote_consumer` 若保留豁免需单独说明
- ~~测试目录约束 `tests/server/services/strategy/regime/test_regime.py`~~ → 网格引擎测试已删（`server/tests/strategy` + `tests/server/services/strategy` 随 `aa70dae` 删除）

## 保留（未变）

- 5 层模块契约 + 单向依赖（services / api / tables 分层不变）
- script_strategy（v90）与其余 services 层模块
