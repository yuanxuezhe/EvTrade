# spec-delta: strategy-exec（现有 spec 增量）

## MODIFIED Requirements

### 与旧网格策略引擎的关系 — 已删除

> **变更说明（2026-08-10）**：commit `aa70dae` 删除了旧网格策略引擎（strategy / regime / grid / audit）。strategy-exec spec 原引用"网格策略引擎（仍在 EvTrade 进程内）"已过时，"网格策略独立化"后续计划作废。

修正以下引用：

- ~~第 253 行 "网格策略引擎（仍在 EvTrade 进程内）：`strategy/spec.md` REQ-STRAT-001~013"~~ → 网格引擎已删除（commit `aa70dae`）；strategy/spec.md REQ-STRAT-001~013 已标记下线
- ~~第 263 行 "网格策略独立化 | 后续 change"~~ → 网格策略已整体删除，不再有"独立化"计划

## 保留（未变）

- REQ-SE-001~007（Backtrader 引擎 / RabbitMQ 信号 / 用户脚本接口 / 乐观锁）
- 脚本策略（strategy_script 系）为现行唯一策略形态，strategy_exec 服务定位不变
