# 2026-08-12-dashboard-pct-last-asset — 仪表盘百分比被 last_asset=0 冲垮

## Why

用户反馈（2026-08-12）：「仪表盘里面的百分比计算不对」。KPI 卡片趋势百分比
（总资产 `todayPnLPercent` / 今日盈亏 `dayPnlPercent`）显示天文数字。

实测定位（dev 库 + 日志）：

1. **后端主因**：`server/services/rpc_health.py` 每 5s 同步资金 `Assets.upsert_one`
   不含 `last_asset`。`assets.last_asset` 在 MySQL 为 `NOT NULL` 且 `COLUMN_DEFAULT=NULL`
   （ORM `default=0.0` 只是 Python 侧默认，不产生 MySQL 默认值）→
   `upsert_one._get_required_columns` 把它当必填列补 `0.0`，写入
   `ON DUPLICATE KEY UPDATE last_asset = 0.0`。
2. reconcile 日初写好 `last_asset`（日志确认算出 889760000000.00）→ 5s 内被 rpc_health
   冲回 0。
3. **前端次因**：`Dashboard.vue` 两个百分比用 `base = last > 0 ? last : 1`，`last_asset=0`
   时除数是 1 → `盈亏 × 100`，显示天文数字而非隐藏。

## What Changes

### 后端：rpc_health 保留 last_asset（主修复）

`server/services/rpc_health.py` asset sync 在 upsert 前读现有行，把 `last_asset` 携带进
upsert data。语义与既有注释一致：`last_asset` = 期初总资产（日初 reconcile 锁定，当天不变），
实时资金同步不得覆盖它。

```
existing = Assets.query_one(id=1)
last_asset = float(getattr(existing, 'last_asset', 0) or 0) if existing else 0.0
Assets.upsert_one({ id, cash, available, frozen_cash, market_value, total_asset,
                    last_asset, synced_at, synced_from='rpc_sync' })
```

### 前端：last_asset 缺失时隐藏趋势（次修复/防御）

`Dashboard.vue`：
- `todayPnLPercent`：`last_asset <= 0` → 返回 `null`（隐藏趋势 chip），不再除 1
- `dayPnlPercent`：同上（已有 `dayPnlTotal==null → null` 前置）

### 不做的事

- ❌ 不改公式（`盈亏 / 期初总资产` 语义正确，REQ-FE-533 口径）
- ❌ 不改 `upsert_one` 通用语义（影响面大；本次只修唯一 assets 写入方）
- ❌ 不做 `assets.last_asset` 加 MySQL DEFAULT 的迁移（rpc_health 显式携带即可，行为等价）
- ❌ 不处理 prev_close 缺失 / broker 金额 scale（独立数据质量问题，与百分比算法无关）

## 时序

```
do_reconcile 日初 → _update_last_asset 写 last_asset
  → rpc_health 5s 资金同步 upsert 携带 last_asset（不再冲 0）
  → Dashboard todayPnLPercent/dayPnlPercent = 盈亏 / last_asset × 100
  → last_asset 仍缺失(0) → 返回 null 隐藏趋势 chip
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `server/services/rpc_health.py` | asset sync upsert 携带现有 `last_asset` |
| 前端 | `client/src/views/Dashboard.vue` | 两百分比 `last_asset<=0 → null` |
| 知识库 | `openspec/specs/frontend/spec.md` | 新增 REQ-FE：仪表盘趋势百分比口径 + 缺失隐藏 |

## 关联

- 上游：`REQ-FE-533`（当日盈亏口径 / last_asset 期初总资产，v114）；
  `server/models/orm.py:205`（last_asset 列定义）；`server/services/reconcile.py:_update_last_asset`
- 影响面：仪表盘两张 KPI 卡趋势百分比（总资产 / 今日盈亏）
