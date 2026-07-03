## Why

当前 `Position.today_buy` / `Position.today_sell` 自 v5 schema 以来从未被前端消费、也没被 push handler 增量写入，成为**死字段**。

更主要的问题有三：

1. **盘中无调平手段**：当 broker 端发生非成交导致的 vol / cash 漂移（期权行权、ETF 申赎、银证转账、ETF 现金分红等），管理员没有任何渠道把 `Position.vol` / `Position.avl_vol` / `Asset.cash` / `Asset.total_asset` 调回到 broker 真实值。
2. **当日 / 历史耦合**：现有 `Orders.vue` / `Trades.vue` 同时混用"前端持仓缓存 + 历史查询"，page reload 后缓存丢失导致体验割裂。
3. **历史查询缺日期范围**：`GET /api/orders` 与 `GET /api/trades` 不支持 `start_date` / `end_date` / `stock_code` 参数，回看历史委托必须前端循环当日数据，效率低且数据不完整。

## What Changes

### 数据模型
- **BREAKING** 移除 `Position.today_buy` / `Position.today_sell`（v5 schema 遗留，从未被 push / reconcile 写入）
- Position / Asset 不引入新的 `manual_offset_*` 字段；调整直接落到现有的 `vol` / `avl_vol` / `cash` / `total_asset` 四个总量字段上

### API
- 新增 `PUT /api/positions/{stock_code}/adjust` —— 原子增量修改 `Position.vol` / `Position.avl_vol`
- 新增 `PUT /api/asset/adjust` —— 原子增量修改 `Asset.cash` / `Asset.total_asset`
- 扩展 `GET /api/orders` 增加 `start_date` / `end_date` / `stock_code` query 参数（可选）
- 扩展 `GET /api/trades` 增加同上 3 个参数

### 前端页面拆分
- `client/src/views/TradeOrders.vue`（现状：混合当日+历史）→ 拆分为：
  - `TodayOrders.vue` —— 读 Pinia `holdings.orders`，含 IDB 持久化，page reload 自动加载当日数据
  - `HistoryOrders.vue` —— 实时查 `GET /api/orders?start_date=&end_date=&stock_code=`，含查询条件面板
- `client/src/views/TradeTrades.vue`（现状：混合当日+历史）→ 拆分为：
  - `TodayTrades.vue` —— 读 Pinia `holdings.trades`，含 IDB 持久化
  - `HistoryTrades.vue` —— 实时查 `GET /api/trades?start_date=&end_date=&stock_code=`

### IDB 持久化
- 恢复被删除的 `holdings.orders` / `holdings.trades` Pinia → IndexedDB 的 write-through（page reload 后从 IDB 恢复）
- 仅当日数据进 IDB：键包含 `trd_date`，跨日清空

## Capabilities

### New Capabilities
- `asset-position-adjust`: 资金与持仓盘中调平 API（原子 +/-、不存 delta 字段、不留审计 row）
- `intraday-orders-trades-cache`: 当日委托 / 当日成交的前端缓存与 IDB 持久化
- `orders-trades-history-query`: 历史委托 / 历史成交的日期范围 + 证券代码查询

### Modified Capabilities
- `data-model`: 删 `Position.today_buy` / `Position.today_sell` 字段
- `positioning`: 删除 `today_buy` / `today_sell` 的前端展示与推/拍增量语义；新增 manual adjust API 客户端
- `trading`: 委托 / 成交查询接口加日期范围 + 证券代码参数；交易页拆分为当日 / 历史
- `system-init`: day-init reconcile 仍以柜台为权威全表覆盖；调平值会被下次 reconcile 抹掉（不持久化调整）
- `push`: 调平 API 不影响 push 链路；`trd_cfm` 仍保留 Position.vol 增量语义

## Impact

**后端**：
- `server/models/orm.py`: 删 `Position.today_buy` / `today_sell` 列，schema migration
- `server/api/positions.py`（新建）: 调平 API
- `server/api/asset.py`（新建或扩展）: asset 调平 API
- `server/api/orders.py`: orders query 支持日期范围
- `server/api/trades.py`: trades query 支持日期范围
- 测试：`tests/server/api/positions/test_adjust.py`、`tests/server/api/asset/test_adjust.py`、扩展 query 测试

**前端**：
- `client/src/views/`: 4 个新页面文件（拆 + 2）
- `client/src/router/index.js`: 新增 / 拆分路由
- `client/src/stores/holdings.js` + `holdings_bootstrap.js`: 加 IDB 持久化钩子
- `client/src/stores/holdings_log.js` 或新 `holdings_idb.js`: IDB 包装模块
- 现有 `Orders.vue` / `Trades.vue` 删除或改为兼容 redirect

**风险**：
- **BREAKING**: 删 `Position.today_buy` / `today_sell` 需要 schema migration；DB 中已有列需 ALTER TABLE DROP COLUMN
- 现有 `Orders.vue` / `Trades.vue` 调用方需要同步迁移
- 调平值不持久化 — 用户对调平窗口期需要文档化（reconcile 一冲即无）
