# Proposal: stock-info-crawler

> **Change**: `2026-07-10-stock-info-crawler`
> **Date**: 2026-07-10
> **Owner**: Hermes + User
> **Status**: draft

## Why

EvTrade 当前缺少股票基础信息(行业/市值/PE/PB/公司简介)的数据源。`positions.stock_name` 字段虽存股票名但空(因 xtquant 行情无基本面),导致前端 Holdings/Trade 等页面无法做行业筛选 / 概念归类 / 选股可视化。

**目标**:从东方财富抓取股票基础信息,落库到新表 `stocks`,前端可在 `/admin/sync` 页面手动触发同步,通过新 WS 频道 `/ws/sync_update` 实时推送同步进度,完成后推送 `stock_synced` 单只详情,前端缓存即时刷新。

## What Changes

### 数据层(Commit 1)
- 新表 `stocks`:存股票基础信息(stock_code PK + 13 个业务字段)
- 新 ORM `server/models/orm.py`:+ `Stock` class
- 新 migration `server/migrations/2026-07-10-create-stocks-table.py`:DDL
- 新 repo `server/repo/stocks.py`:upsert + list_by_industry + get_by_code

### 业务层(Commit 2)
- 新 `server/crawler/sources/eastmoney.py`:东方财富 API 适配(基本信息 + 公司简介)
- 新 `server/crawler/runner.py`:异步同步循环 + 进度回调
- 新 `server/services/sync/manager.py`:任务生命周期(start/stop/status)
- 新 `server/services/sync/task.py`:单次同步任务
- 新 `server/api/sync.py`:`POST /api/sync/stocks`(start),`DELETE`(stop),`GET /api/sync/stocks/status`
- 新 `server/api/stocks.py`:`GET /api/stocks/{code}`,`GET /api/stocks`(列表)
- 新 WS 频道 `/ws/sync_update`(admin only,独立于 `/ws/quote_update`)
- 新 `tests/test_crawler_eastmoney.py` + `tests/test_sync_manager.py`

### 前端层(Commit 3)
- 新 `client/src/views/Sync.vue`:进度管理页面(admin 角色可见)
- 新 `client/src/api/sync.js`:REST 调用
- 新 `client/src/stores/sync.js`:Pinia store + WS 订阅
- 新 `client/src/stores/stocks.js`:股票信息缓存(被 WS 推送更新)
- 新路由 `/admin/sync` + 菜单项(admin 守卫)

## Non-Goals

- **不爬历史财务数据**(只爬当前 snapshot)
- **不做增量爬取**(首次 backfill 全市场,后续手动触发刷新)
- **不做实时行情拉取**(已有 hqserver 负责)
- **不做多数据源切换**(v1 只支持东方财富)

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  同步流程                                                     │
├──────────────────────────────────────────────────────────────┤
│  Admin 点击 "开始同步"                                         │
│       │                                                       │
│       ▼                                                       │
│  POST /api/sync/stocks                                        │
│       │  (admin JWT 鉴权)                                     │
│       ▼                                                       │
│  sync_manager.start()                                         │
│       │                                                       │
│       ├─▶ 创建后台 asyncio.Task                               │
│       │                                                       │
│       └─▶ runner.run():                                       │
│             for stock_code in all_codes:                      │
│                 data = eastmoney.fetch(stock_code)            │
│                 repo.upsert(stocks, data)                     │
│                 progress_callback(progress_dict)              │
│                     │                                         │
│                     └─▶ ws sync_update 广播                   │
│                          ├─ stock_sync_progress (1Hz)         │
│                          └─ stock_synced (per stock)          │
└──────────────────────────────────────────────────────────────┘
```

## Risks

| 风险 | 缓解 |
|---|---|
| 全市场 ~5400 只 × 0.5s sleep = 45min 慢 | 进度实时 WS 推送,UI 显示 ETA |
| 同步期间前端刷新页面 | 后台 task 独立于 WS 订阅,继续跑 |
| 同步期间重启 backend | 任务丢失(内存 task,接受) |
| 反爬封 IP | 单线程 + 随机 UA + sleep 0.5s + User-Agent |
| 东方财富改版 API 失效 | 数据源适配集中在 `crawler/sources/eastmoney.py` 一个文件 |
| 字段值类型异常(空字符串/None) | 应用层做类型转换 + try/except 跳过 |

## Migration Plan

1. Step 1: 跑 `server/migrations/2026-07-10-create-stocks-table.py` 创建表(幂等)
2. Step 2: 首次同步启动 → backfill 全市场 ~5400 只
3. Step 3: 数据稳定后,可加 cron daily 增量刷新(本次不做)

## Out of Scope (Future)

- 多数据源(新浪/同花顺/雪球)
- 财务三表(资产负债表/利润表/现金流量表)
- 概念板块 / 题材概念
- 资讯新闻爬取