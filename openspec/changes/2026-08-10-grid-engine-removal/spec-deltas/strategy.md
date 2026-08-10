# spec-delta: strategy（现有 spec 增量）

## REMOVED Requirements

### REQ-STRAT-001 ~ REQ-STRAT-013（网格策略引擎 regime/grid）— 已删除

> **变更说明（2026-08-10）**：旧网格策略引擎（`Strategy` / `StrategyRegime` / `StrategyGrid` / `StrategyAudit`）已被 commit `aa70dae` **彻底删除**：后端删 41 文件（`server/api/strategy/` + `server/services/strategy/` 死代码 + `server/tables/strategy*.py`），前端删 12 文件（`StrategyTrade.vue` / `stores/strategy.js` / `api/strategy.js` / `strategy_update` WS 频道 / `/strategy-trade` 路由），DB 迁移 `2026-08-10-drop-legacy-strategy-tables.py` 已 DROP 5 张表。
>
> 网格引擎被**脚本策略**（`strategy_script` 系，REQ-STRAT-014~017，引擎已迁独立服务 `strategy_exec/`）取代。`/api/strategy/*`（CRUD / control / audit / flags / t0）端点全部下线，`STRATEGY_ENGINE_ENABLED` 灰度门已移除。

以下 13 个 Requirement **从本 spec 删除**（已下线）：

- ~~REQ-STRAT-001: 策略 CRUD~~（`/api/strategy` 端点已删）
- ~~REQ-STRAT-002: 9 种 flag 注册表~~（`/api/strategy/flags` 已删）
- ~~REQ-STRAT-003: 4 张 ORM 表~~（Strategy / StrategyRegime / StrategyGrid / StrategyAudit 已 DROP）
- ~~REQ-STRAT-004: regime 匹配规则~~
- ~~REQ-STRAT-005: regime 冷却（防抖）~~
- ~~REQ-STRAT-006: grid 决策 — 底仓保护 + 整手~~
- ~~REQ-STRAT-007: engine 评估入口~~（`server/services/strategy/engine.py` 已删）
- ~~REQ-STRAT-008: quote_consumer 首次 WS 接入~~（已重写为纯行情快照 + `quote_update` 广播）
- ~~REQ-STRAT-009: REST API（8 端点）~~
- ~~REQ-STRAT-010: control action 语义~~
- ~~REQ-STRAT-011: WS payload `strategy_update` 频道~~（频道已从 `ws_manager.active_connections` 移除）
- ~~REQ-STRAT-012: Order.user_def 关联~~
- ~~REQ-STRAT-013: T0 端点 JOIN 迁移~~（`api/strategy/t0_endpoints.py` 已删；T0 交易走 `t0_tasks` 体系）

## MODIFIED Requirements

### 标题 + Purpose（网格引擎 → 已下线）

- 标题：`# strategy — 网格策略交易引擎` → `# strategy — 策略交易引擎（网格引擎已下线）`
- Purpose：开头加说明，本 spec 现主要覆盖 **脚本策略模块**（REQ-STRAT-014~017）；REQ-STRAT-001~013 网格引擎历史正文保留但标记已删除
- 顶部 DB schema 引用：`data-model/spec.md §4（Strategy / StrategyRegime / StrategyGrid / StrategyAudit）` → 修正为脚本策略表引用

## 保留（未变）

- REQ-STRAT-014 ~ REQ-STRAT-017（脚本策略模块，v90 + v120）— 现行，引擎在 `strategy-exec/spec.md`
- Cross References 部分 — 同步修正对已删网格条目的引用
