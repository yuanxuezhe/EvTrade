# 2026-07-12-slim-stocks-table — 证券信息表瘦身

## Why

当前 `stocks` 表（v21 stock-info-crawler）14 个字段，引入 6 个新字段（industry/sector/market/intro/total_share 等），但实际项目只用 `stock_name` 做下单辅助显示，其他字段都是"为展示而展示"：
- **行业/市值/PE/PB/公司简介** — 爬虫入仓但前端从未消费
- **板块/上市日期/总股本/流通股本** — 同步任务期间被爬虫塞进表，污染了 23 行种子数据
- 这些"信息"对日内 T0 交易没有业务价值

用户原话（2026-07-12）："证券信息表只保留证券代码，证券名称，板块，回转标志，最小买入数量，买卖单位2，修改表后优化代码适配"

## What Changes

按用户拍板（Q1-Q6 拍板清单），精简 stocks 表：

| 操作 | 字段 | 来源 |
|---|---|---|
| **保留** | `stock_code` (PK) | 业务必需 |
| **保留** | `stock_name` (VARCHAR(64) NOT NULL DEFAULT '') | 业务必需（下单显示）|
| **保留** | `sector` (VARCHAR(64)) | 用户指定「板块」= sector 申万二级 |
| **新增** | `is_t0_able` (BOOLEAN NOT NULL DEFAULT FALSE) | 回转标志 — 默认 false |
| **新增** | `min_buy_qty` (INT NOT NULL DEFAULT 100) | 最小买入数量 — A 股默认 100 |
| **新增** | `trade_unit` (INT NOT NULL DEFAULT 1) | 买卖单位 — 序号无义，默认 1 |
| **删除** | `industry`, `market`, `list_date`, `total_share`, `float_share`, `market_cap`, `pe_ratio`, `pb_ratio`, `intro` | 用户指令"只保留" |

### 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| migration | `server/migrations/2026-07-12-slim-stocks-table.py` | 新增：DROP 9 列 + ADD 3 列 + INDEX 清理 |
| backup | 同上 | 先 `CREATE TABLE stocks_legacy AS SELECT * FROM stocks` 保留历史数据 |
| ORM | `server/models/orm.py` | Stock 类：移除 9 字段、加 3 字段、删 2 索引 |
| repo | `server/repo/stocks.py` | `_ADMIN_EDITABLE_FIELDS`、`to_dict`、`to_dict_from_data` 同步字段 |
| API | `server/api/stocks.py` | `StockUpdateRequest` 白名单更新 |
| crawler | `server/crawler/sources/eastmoney.py` | `fetch_base_info` 不再返回 9 个字段，只返 stock_name/sector |
| runner | `server/crawler/runner.py` | WS `stock_synced` payload 字段同步 |
| frontend api | `client/src/api/stocks.js` | 接口契约同步（如果需要）|
| frontend store | `client/src/stores/stocks.js` | `editForm` / 列表 row 字段同步 |
| frontend view | `client/src/views/AdminStockConfig.vue` | 表格列、编辑弹窗、筛选条全部同步 |
| spec | `openspec/specs/data-model/spec.md` §13 | 字段表更新 |
| spec | `openspec/specs/stocks/spec.md` REQ-STOCK-005 | 字段映射更新 |

### 数据备份策略

按 Q4 = B：`CREATE TABLE stocks_legacy AS SELECT * FROM stocks` — 把当前 23 行完整数据拷到 `stocks_legacy` 表保留可查，**不**DROP 原始数据后再转存。

### 影响面

- **能力**：stocks capability（REQ-STOCK-001/002/003/004/005）
- **业务影响**：前端 `/admin/stock-config` 页面筛选从 industry 改为 sector；编辑弹窗字段缩减到 5 个；爬虫不再入仓行业/市值等冗余数据
- **API**：`GET /api/stocks` 返回字段裁剪；`PATCH /api/stocks/{code}` 白名单更新
- **DB**：迁移 + DDL ALTER（idempotent）
- **风险**：中 — 字段裁剪影响 5 个文件 + spec 2 处 + 前端 3 处，但每个 commit 可单独 revert
- **可回滚**：每 commit 独立可 revert；stocks_legacy 表永久保留

## Tasks

- [ ] 1. 写 OpenSpec 4 件套（proposal + tasks + spec-deltas/data-model.md + spec-deltas/stocks.md）
- [ ] 2. **Commit 1** — migration: DROP 9 列 + ADD 3 列 + stocks_legacy 备份
- [ ] 3. **Commit 2** — orm: Stock 类字段同步 + index 清理
- [ ] 4. **Commit 3** — repo: `_ADMIN_EDITABLE_FIELDS` + `to_dict` 系列同步
- [ ] 5. **Commit 4** — api + crawler: `StockUpdateRequest` + eastmoney.py 字段映射 + runner WS payload
- [ ] 6. **Commit 5** — frontend: stores/stocks.js + AdminStockConfig.vue 表格 + 弹窗 + 筛选
- [ ] 7. **Commit 6** — docs: data-model §13 + stocks spec REQ-STOCK-005 更新
- [ ] 8. 验证：跑 migration + 重启 backend + 浏览器手测 `/admin/stock-config` admin 登录
- [ ] 9. **不自动 push** — 等用户拍板

## 关联

- `openspec/specs/data-model/spec.md` §13 (stocks 表)
- `openspec/specs/stocks/spec.md` REQ-STOCK-001/002/005
- `server/models/orm.py:363` (Stock 类)
- `server/repo/stocks.py:24-150` (upsert/get/list/to_dict)
- `server/api/stocks.py:72-87` (StockUpdateRequest)
- `server/crawler/sources/eastmoney.py:74-132` (字段映射)
- `server/crawler/runner.py:118-124` (WS stock_synced payload)
- `client/src/stores/stocks.js:50-64` (editForm)
- `client/src/views/AdminStockConfig.vue` (表格 + 弹窗 + 筛选)