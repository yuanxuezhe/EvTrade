# grid-engine-removal — 旧网格策略引擎(regime/grid)删除后的知识库同步

> **作者**: Hermes
> **日期**: 2026-08-10
> **状态**: 待实施（实施后归档）

## 为什么改（Why）

### 问题陈述

commit `aa70dae`（2026-08-10）已**彻底删除旧网格策略引擎**（`Strategy` / `StrategyRegime` / `StrategyGrid` / `StrategyAudit`）：后端删 41 文件（`api/strategy/` + `services/strategy/` 死代码 + `tables/strategy*.py`），前端删 12 文件（`StrategyTrade.vue` / `stores/strategy.js` / `api/strategy.js` / `strategy_update` WS 频道等），DB 迁移 `2026-08-10-drop-legacy-strategy-tables.py` 已 DROP 5 张表（strategy / strategy_regime / strategy_grid / strategy_audit / stocks_legacy）。

但**知识库（openspec specs + schema.yml + docs）仍把网格引擎描述为"现行"**：

- `server/schema.yml` 仍含 4 张已删表定义（strategy / strategy_audit / strategy_grid / strategy_regime）— **这是实际风险**：再跑 `sync_schema.py apply` 会重建已被 DROP 的表
- `openspec/specs/strategy/spec.md` REQ-STRAT-001~013 整段描述已删的网格引擎，标题仍是"网格策略交易引擎"
- `data-model` / `configuration` / `frontend` / `push` / `ws-protocol` / `server-architecture` / `strategy-exec` / `README` 多份 spec 引用已删的 `/api/strategy`、`strategy_update` 频道、`STRATEGY_ENGINE_ENABLED`、`server/services/strategy/regime.py` 等
- `docs/strategy_trading_guide.md` 整篇是已删接口（网格策略 + `/api/strategy/t0`）的用户指南

### 解决方案

本次 change **只同步知识库到实际状态**，不再动任何业务代码（删除已在 `aa70dae` 完成）：

1. `server/schema.yml` 移除 4 张已删表（19 → 15 张），与 DB 现状对齐
2. `strategy/spec.md` 把 REQ-STRAT-001~013 标记为**已删除**（保留历史正文 + 删除说明），标题改为"策略交易引擎（网格引擎已下线）"
3. 其余 8 份 spec + README 清理对已删网格引擎的引用
4. `docs/strategy_trading_guide.md` 顶部加"已下线"横幅 + 指向现行脚本策略文档，`docs/index.md` 同步

## 范围（Scope）

### 包含（In）

| 项 | 详情 |
|---|---|
| `server/schema.yml` | 删 `strategy` / `strategy_audit` / `strategy_grid` / `strategy_regime` 4 张表定义（**不跑 apply**，DB 已对齐）|
| `openspec/specs/strategy/spec.md` | 网格部分（REQ-STRAT-001~013）标记已删除 + 标题/DB 引用修正 |
| `openspec/specs/data-model/spec.md` | 表概览删 4 行 + 计数 19→15 + 变更说明补 drop 条目 |
| `openspec/specs/configuration/spec.md` | 删 `STRATEGY_ENGINE_ENABLED` 灰度门描述 |
| `openspec/specs/frontend/spec.md` | REQ-FE-310（/strategy-trade 路由 + strategy_update WS）标记已删 |
| `openspec/specs/push/spec.md` | REQ-PUSH-040（strategy_update 频道）标记已删 |
| `openspec/specs/ws-protocol/spec.md` | `strategy_update` / `t0_strategy_update` 引用清理 |
| `openspec/specs/server-architecture/spec.md` | 对已删 strategy 子模块 / `api/strategy.py` 引用修正 |
| `openspec/specs/strategy-exec/spec.md` | "网格策略引擎（仍在 EvTrade 进程内）"→ 已删除 + 后续独立化计划作废 |
| `openspec/specs/README.md` | strategy 行描述改为"脚本策略 + 已下线网格" |
| `docs/strategy_trading_guide.md` + `docs/index.md` | 已下线横幅 + 描述同步 |

### 不包含（Out）

- 不改任何业务代码（`aa70dae` 已删干净）
- 不动历史文档（`docs/CHANGELOG_v81.md` / `docs/changelog/*` / `KNOWLEDGE_GAP_AUDIT.md` / 迁移脚本）
- 不跑 `sync_schema.py apply`（DB 已是目标状态）
- 不重建 `server/tables/strategy*.py`（4 张已删表的 ORM 已随 `aa70dae` 删除）

## 关键决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | schema.yml 只删不跑 apply | DB 迁移已在 `aa70dae` 执行；schema.yml 仅是 SoT 对齐，避免碰生产 |
| D2 | 网格 spec 保留正文 + 标记删除，而非整段删除 | OpenSpec 原则：spec 演进史是"为什么这样决策"的证据（同 `docs/specs-history/` 思路）|
| D3 | `strategy_trading_guide.md` 加横幅保留，不删除 | `docs/` 静态沉淀体系保留历史；现行指南已有 `docs/strategy-migration-v90-to-bt.md` |

## 相关

- 删除 commit：`aa70dae`（refactor(strategy): 清理旧网格策略引擎(regime/grid) — 删 62 文件 + 5 张空表）
- DB 迁移：`server/migrations/2026-08-10-drop-legacy-strategy-tables.py`
- 现行脚本策略引擎：`openspec/specs/strategy-exec/spec.md`（REQ-SE-001~007）
