# Tasks — 仪表盘百分比被 last_asset=0 冲垮

> 根因：rpc_health 5s 资金同步 upsert 不含 last_asset → MySQL 无默认值 → ON DUPLICATE KEY
> UPDATE 把它冲回 0 → 前端 `base = last>0?last:1` 除 1 → 天文数字百分比。
> 改动分 commit 便于 review/回滚。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 主 spec 落地：`openspec/specs/frontend/spec.md` 新增 REQ-FE 仪表盘趋势百分比口径
      - last_asset = 期初总资产（日初 reconcile 锁定，当天不变），rpc_health 实时同步必须保留
      - 百分比 = 盈亏 / last_asset × 100；last_asset 缺失(0) → 隐藏趋势 chip（返回 null）
- [x] 1.3 commit: `docs(spec): 仪表盘趋势百分比 last_asset 口径 + 缺失隐藏 (dashboard-pct-last-asset)`（598db4e）

## 2 — 后端修复（rpc_health 保留 last_asset）

- [x] 2.1 `server/services/rpc_health.py`：asset sync upsert 前读现有行 `last_asset` 并携带
- [x] 2.2 commit: `fix(backend): rpc_health 资金同步保留 last_asset, 不再冲回 0`（edd6f11）

## 3 — 前端修复（last_asset 缺失隐藏趋势）

- [x] 3.1 `client/src/views/Dashboard.vue`：`todayPnLPercent` / `dayPnlPercent` `last_asset<=0 → null`
- [x] 3.2 commit: `fix(client): 仪表盘趋势百分比 last_asset 缺失时隐藏, 不再除 1`（9c68a32）

## 4 — 测试

- [x] 4.1 后端：`test_cost_price_round4.py` 4/4 通过（无 regression）
- [x] 4.2 前端：t0-calc 43/43 + daypnl_livepush 2/2 通过（Dashboard 无单测, 逻辑为纯 computed null 兜底）
