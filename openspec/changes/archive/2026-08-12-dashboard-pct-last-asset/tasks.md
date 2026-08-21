# Tasks — 仪表盘百分比被 last_asset=0 冲垮（最终口径: 前一日总资产）

> 根因：rpc_health 5s 资金同步 upsert 不含 last_asset → MySQL 无默认值 → ON DUPLICATE KEY
> UPDATE 把它冲回 0 → 前端 `base = last>0?last:1` 除 1 → 天文数字百分比。
> **最终口径（2026-08-13 用户）**：「总资产-当日盈亏就是前一日的总资产」→ 分母 =
> 总资产 − 当日盈亏，前端不再依赖 last_asset。改动分 commit 便于 review/回滚。

## 0 — 最终口径修正（2026-08-13）

- [x] 0.1 用户口径：趋势百分比分母 = 前一日总资产 = 总资产 − 当日盈亏，不依赖 last_asset
- [x] 0.2 spec REQ-FE-535 修正（前一日总资产口径 + 缺失/分母≤0 隐藏）；proposal 同步（c0aba9b）
- [x] 0.3 commit: `fix(client): 仪表盘趋势百分比改前一日总资产口径 (总资产−当日盈亏), 不依赖 last_asset`（f42da03）
- [x] 0.4 测试复验：t0-calc + daypnl_livepush 45/45 通过；Dashboard.vue SFC parse OK

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 主 spec 落地：`openspec/specs/frontend/spec.md` REQ-FE 仪表盘趋势百分比口径
      - v1: last_asset 口径（保留 rpc_health last_asset）；v2: 前一日总资产口径（最终）
- [x] 1.3 commit: `docs(spec): 仪表盘趋势百分比 last_asset 口径 + 缺失隐藏 (dashboard-pct-last-asset)`（598db4e）

## 2 — 后端修复（rpc_health 保留 last_asset）

- [x] 2.1 `server/services/rpc_health.py`：asset sync upsert 前读现有行 `last_asset` 并携带
- [x] 2.2 commit: `fix(backend): rpc_health 资金同步保留 last_asset, 不再冲回 0`（edd6f11）
      （last_asset 仍作数据模型字段，供 CacheAsset 展示 / ws asset_update；不再参与趋势计算）

## 3 — 前端修复

- [x] 3.1 `client/src/views/Dashboard.vue`：`todayPnLPercent` / `dayPnlPercent` `last_asset<=0 → null`
- [x] 3.2 commit: `fix(client): 仪表盘趋势百分比 last_asset 缺失时隐藏, 不再除 1`（9c68a32）
- [x] 3.3 **最终口径**：移除 `todayPnL`；`prevDayTotalAsset = 总资产 − 当日盈亏`；
      `dayPnlPercent`/`todayPnLPercent` = `当日盈亏 / prevDayTotalAsset × 100`，
      当日盈亏缺失或分母≤0 → null 隐藏
- [x] 3.4 commit: `fix(client): 仪表盘趋势百分比改前一日总资产口径 (总资产−当日盈亏), 不依赖 last_asset`（f42da03，对应 0.3）

## 4 — 测试

- [x] 4.1 后端：`test_cost_price_round4.py` 4/4 通过（无 regression）
- [x] 4.2 前端：t0-calc 43/43 + daypnl_livepush 2/2 通过（Dashboard 无单测, 逻辑为纯 computed）
- [x] 4.3 最终口径复验：Dashboard.vue 改动后 t0-calc + daypnl_livepush 45/45 通过
