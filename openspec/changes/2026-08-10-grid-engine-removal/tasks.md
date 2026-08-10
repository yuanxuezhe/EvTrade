# tasks.md — grid-engine-removal

> 知识库同步 change（无业务代码改动）。删除已在 commit `aa70dae` 完成，本次只对齐 specs / schema.yml / docs。

## Phase 1: schema.yml 对齐（1 项）

- [x] 1.1 `server/schema.yml` 删除 `strategy` / `strategy_audit` / `strategy_grid` / `strategy_regime` 4 张表定义（19 → 15 张），不跑 `sync_schema.py apply`
  - [x] 1.1.1 确认 `server/tables/` 无这 4 张表 ORM（应只有 strategy_script / strategy_script_audit / strategy_task）
  - [x] 1.1.2 确认 DB 侧表已 DROP（`2026-08-10-drop-legacy-strategy-tables.py` 已执行）

## Phase 2: openspec specs 同步（9 项）

- [x] 2.1 `openspec/specs/strategy/spec.md` — 标题 + Purpose 改为"网格引擎已下线"；REQ-STRAT-001~013 前加删除横幅；header DB schema 引用修正
- [x] 2.2 `openspec/specs/data-model/spec.md` — 表概览删 strategy / strategy_grid / strategy_regime / strategy_audit 4 行 + 计数 19→15 + 变更说明补 drop 条目
- [x] 2.3 `openspec/specs/configuration/spec.md` — 删 `STRATEGY_ENGINE_ENABLED` 灰度门描述（REQ-CFG-008 区域）
- [x] 2.4 `openspec/specs/frontend/spec.md` — REQ-FE-310（/strategy-trade 路由 + strategy_update WS + StrategyTrade.vue）标记已删
- [x] 2.5 `openspec/specs/push/spec.md` — REQ-PUSH-040（strategy_update 频道）+ 344/358/363/368 行引用清理
- [x] 2.6 `openspec/specs/ws-protocol/spec.md` — `strategy_update` / `t0_strategy_update` 引用清理（t0 引擎也已删）
- [x] 2.7 `openspec/specs/server-architecture/spec.md` — 已删 strategy 子模块（regime/grid/engine）+ `api/strategy.py` 引用修正
- [x] 2.8 `openspec/specs/strategy-exec/spec.md` — "网格策略引擎（仍在 EvTrade 进程内）"→ 已删除；"网格策略独立化"后续计划作废
- [x] 2.9 `openspec/specs/README.md` — strategy 行描述"网格策略引擎 + script-strategy"→ 更新为"脚本策略 + 已下线网格"

## Phase 3: docs 同步（2 项）

- [x] 3.1 `docs/strategy_trading_guide.md` — 顶部加"已下线"横幅，指向 `docs/strategy-migration-v90-to-bt.md` + `docs/index.md`
- [x] 3.2 `docs/index.md` — strategy_trading_guide.md 描述同步为"已下线历史指南"

## Phase 4: 收尾（2 项）

- [x] 4.1 交叉核对：grep 全库确认无"网格引擎仍现行"的残留描述（KNOWLEDGE_GAP_AUDIT / changelog / 迁移脚本除外）
- [x] 4.2 归档 `openspec/changes/2026-08-10-grid-engine-removal` → `openspec/changes/archive/`，所有 task 打勾
