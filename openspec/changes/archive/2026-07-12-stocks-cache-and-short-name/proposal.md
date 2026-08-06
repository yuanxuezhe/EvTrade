# Proposal: stocks 全量缓存 + 拼音简称 + 真分页 + autocomplete 输入

**Change ID**: `2026-07-12-stocks-cache-and-short-name`
**Date**: 2026-07-12
**Status**: Proposed

## 背景

v23 slim-stocks-table 把 stocks 表精简到 6 业务字段后，stocks 表存量 5529 行（沪深京 A 股）。
前端 AdminStockConfig.vue 拉列表时硬塞 `limit: 1000`，命中 1000 后不再返回（**不是后端限制**，
是前端硬编码）。随着 stocks 表行数增长（v24 已经塞了 5529，将来 v25 加 ETF 会破 6000），
硬上限 1000 不再够。

**用户原话（2026-07-12）**：
1. "前端增加缓存，缓存证券信息，且必须全量"
2. "前端通过分页的方式，循环查证券信息，一次100条"
3. "界面查询页面显示的证券信息，是查的后端，分页查询"
4. "修正的时候，同时刷新缓存和数据库"
5. "前端证券信息输入组件，支持输入证券代码、证券名称、首字母等，筛选证券代码"
6. "后端数据库增加证券简称字段，填入名称拼音首字母，用来快速通过首字母筛选"
7. "需要筛选缓存中的证券信息，必须输入存在的证券代码"

## 目标

### 1. 后端 stocks 表加 `short_name` 字段
- 名称拼音首字母（如「平安银行」→ `PAYH`）
- 用作首字母快速筛选前缀匹配
- 一次性脚本灌入 5529 行存量数据

### 2. 后端 `GET /api/stocks` 支持真分页
- 新增 `page`（默认 1）/ `page_size`（默认 100）
- `limit` 参数保留兼容（v23 客户端仍能用）
- 返回 `{code, msg, list, total}`，前端用 `total` 渲染 pagination

### 3. 前端 stocks store 加全量缓存
- 内存缓存 `cache: Stock[]`（全量 5529）
- `loadCache()` 循环 `?page=N&page_size=100` 拉到 5529
- AdminStockConfig 表格直接走后端分页 (`pageRows`/`total`/`fetchPage`)
- PATCH 时**同时**更新 `cache` 和 `pageRows` 对应行

### 4. 新增 `<StockCodeAutocomplete>` 组件
- props: `modelValue: string` / `placeholder` / `disabled`
- emit: `update:modelValue` / `select(stock)`
- 内置三路筛选：`stock_code` 前缀 OR `stock_name` 含 OR `short_name` 前缀
- 必须命中真实存在的 stock_code 才允许选中（无效输入时不 emit select）
- 默认 10 条候选，最多展示 50 条

## 范围

### In Scope
- DB schema: 加 `short_name VARCHAR(16) NULL` 字段
- Migration: 2026-07-12-add-short-name-to-stocks
- ORM: `Stock.short_name` 字段
- Repo: `to_dict` 加 short_name；admin 白名单加 short_name
- API:
  - `GET /api/stocks` 加 `page/page_size` 参数 + `total` 返回
  - `PATCH /api/stocks/{code}` 白名单加 short_name
- 一次性脚本: `server/scripts/backfill_short_name.py`
- 前端 stocks store 重构：cache + pageRows + total
- 前端 AdminStockConfig.vue：表格分页走后端 + autocomplete 替换 stock_code 输入
- 新组件: `client/src/components/StockCodeAutocomplete.vue`
- OpenSpec 主体 spec 同步

### Out of Scope (本次 v25 不做)
- ❌ 移除 sync 任务（用户提到但**独立 v26 change**，本次不动）
- ❌ autocomplete 在 orders / positions / holdings 录入页面使用（v27 范围）
- ❌ admin 重生成 short_name 接口（用户说"自己去维护"，脚本即可）
- ❌ localStorage 持久化缓存（内存缓存足够，刷新页面重拉 ~18s 可接受）
- ❌ sector 字段兜底填充（v24 已知问题，留 v28）

## 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| `pypinyin` 库未装 | 低 | pip install pypinyin ~150KB |
| migration 加列时锁表 | 低 | 5529 行秒级，MySQL 8.0 INSTANT DDL |
| 前端 cache 一次性加载 ~18s | 低 | 加 loading + 进度条，分页循环不阻塞 UI |
| PATCH 时 cache 与 pageRows 不同步 | 中 | store.updateStock 同时更新两处 |
| autocomplete 三路 OR 在 5529 行上性能 | 低 | 用 Array.filter，单次筛选 < 50ms |
| 旧 `limit` 参数兼容 | 低 | 后端保留，老客户端 `?limit=1000` 仍能用 |

## Commit 拆分（v25 stocks-cache-and-short-name）

按 implementation-workflow §A.1，每个 commit 独立可 revert：

1. `chore(openspec): 新增 2026-07-12-stocks-cache-and-short-name change 4 件套`
2. `feat(db): migration 加 short_name 字段 + 安装 pypinyin`
3. `feat(orm+repo): Stock.short_name + admin 白名单 + to_dict 字段`
4. `feat(api): /api/stocks 真分页 page/page_size + 返回 total + 白名单 short_name + backfill 脚本`
5. `feat(client): 全量缓存 + 翻页走后端 + StockCodeAutocomplete 组件`
6. `docs(openspec): 归档 change + 同步 stocks/spec.md + data-model/spec.md §13`

## 验证

- Migration: `python3 server/migrations/2026-07-12-add-short-name-to-stocks.py` 幂等
- Backfill: `python3 server/scripts/backfill_short_name.py` 灌入 5529 行
- API: `curl /api/stocks?page=1&page_size=20` 返回 `{list, total: 5529}`
- 前端 cache: AdminStockConfig onMounted 后 `store.cache.length === 5529`
- Autocomplete: 输入「000001」→ 候选 1 条；输入「PAYH」→ 候选「平安银行」
- PATCH: 修改后 `cache` 和 `pageRows` 同步刷新