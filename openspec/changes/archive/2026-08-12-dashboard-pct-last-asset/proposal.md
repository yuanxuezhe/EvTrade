# 2026-08-12-dashboard-pct-last-asset — 仪表盘百分比被 last_asset=0 冲垮

## Why

用户反馈（2026-08-12）：「仪表盘里面的百分比计算不对」。KPI 卡片趋势百分比
（总资产 `todayPnLPercent` / 今日盈亏 `dayPnlPercent`）显示天文数字。

实测定位（dev 库 + 日志）：

1. **后端根因**：`server/services/rpc_health.py` 每 5s 同步资金 `Assets.upsert_one`
   不含 `last_asset`。`assets.last_asset` 在 MySQL 为 `NOT NULL` 且 `COLUMN_DEFAULT=NULL`
   （ORM `default=0.0` 只是 Python 侧默认，不产生 MySQL 默认值）→
   `upsert_one._get_required_columns` 把它当必填列补 `0.0`，写入
   `ON DUPLICATE KEY UPDATE last_asset = 0.0`。
2. reconcile 日初写好 `last_asset`（日志确认算出 889760000000.00）→ 5s 内被 rpc_health
   冲回 0。
3. **前端次因**：`Dashboard.vue` 两个百分比用 `base = last > 0 ? last : 1`，`last_asset=0`
   时除数是 1 → `盈亏 × 100`，显示天文数字而非隐藏。

## 最终口径（2026-08-13 用户确认）

「**总资产 - 当日盈亏就是前一日的总资产，用这个值算比例**」——趋势百分比分母 =
前一日总资产 = 总资产 − 当日盈亏，**不再依赖 last_asset**（前端不再受 rpc_health
冲 0 影响）：

```
趋势百分比 = 当日盈亏 / (总资产 − 当日盈亏) × 100
```

- 总资产 = `holdings.liveTotalAsset`（实时，兜底后端 `total_asset`）
- 当日盈亏 = `Σ positions[].day_pnl`（`dayPnlTotal`）
- 当日盈亏缺失 或 分母 ≤ 0 → 返回 `null`（隐藏趋势 chip），不除 1

## What Changes

### 后端：rpc_health 保留 last_asset（数据模型修复）

`server/services/rpc_health.py` asset sync 在 upsert 前读现有行，把 `last_asset` 携带进
upsert data，不再冲回 0。`last_asset` 仍作为数据模型字段（CacheAsset 展示「期初总资产」、
ws asset_update），只是**不再参与仪表盘趋势计算**。

```
existing = Assets.query_one(id=1)
last_asset = float(getattr(existing, 'last_asset', 0) or 0) if existing else 0.0
Assets.upsert_one({ id, cash, available, frozen_cash, market_value, total_asset,
                    last_asset, synced_at, synced_from='rpc_sync' })
```

### 前端：趋势百分比改用前一日总资产（2026-08-13 最终口径）

`Dashboard.vue`：
- 移除 `todayPnL`（`总资产 − last_asset`，已废弃）
- 新增 `prevDayTotalAsset = 总资产 − 当日盈亏`（`dayPnlTotal`）
- `dayPnlPercent` / `todayPnLPercent`（总资产卡趋势 = 同一今日收益率）：
  `当日盈亏 / prevDayTotalAsset × 100`；当日盈亏缺失 或 分母 ≤ 0 → `null` 隐藏

### 不做的事

- ❌ 不改 `upsert_one` 通用语义（影响面大；本次只修唯一 assets 写入方）
- ❌ 不做 `assets.last_asset` 加 MySQL DEFAULT 的迁移（rpc_health 显式携带即可，行为等价）
- ❌ 不处理 prev_close 缺失 / broker 金额 scale（独立数据质量问题，与百分比算法无关）

## 时序

```
do_reconcile 日初 → _update_last_asset 写 last_asset
  → rpc_health 5s 资金同步 upsert 携带 last_asset（不再冲 0, last_asset 字段保持正确）
  → Dashboard: 前一日总资产 = 总资产 − 当日盈亏
  → todayPnLPercent/dayPnlPercent = 当日盈亏 / 前一日总资产 × 100
  → 当日盈亏缺失 或 分母<=0 → null 隐藏趋势 chip
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `server/services/rpc_health.py` | asset sync upsert 携带现有 `last_asset` |
| 前端 | `client/src/views/Dashboard.vue` | 移除 `todayPnL`；趋势百分比 = 当日盈亏 / (总资产 − 当日盈亏) |
| 知识库 | `openspec/specs/frontend/spec.md` | REQ-FE-535 修正：前一日总资产分母口径 + 缺失/分母≤0 隐藏 |

## 关联

- 上游：`REQ-FE-533`（当日盈亏口径 / `Σ day_pnl`）；`server/models/orm.py:205`（last_asset 列）；
  `server/services/rpc_health.py`（5s 资金同步）
- 影响面：仪表盘两张 KPI 卡趋势百分比（总资产 / 今日盈亏）
