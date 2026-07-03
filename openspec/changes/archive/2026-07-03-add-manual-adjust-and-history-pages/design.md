## Context

当前 EvTrade 系统的 3 个结构性冗余 / 缺口：

1. **Position 表 `today_buy` / `today_sell` 是死字段**：v5 schema 以来从未被前端消费、`do_reconcile` 写入后无人读、`pos_cfm` push handler 不写、`trd_cfm` push handler 不增量。`data-model/spec.md` 业务规则仍写着"只由 do_reconcile 设置"，与"无人写也无人读"的事实矛盾。

2. **盘中无调平手段**：当 broker 端发生非成交导致的 vol / cash 漂移（期权行权、ETF 申赎、银证转账、ETF 现金分红、ETF 增发调仓），管理员没有 API 渠道把 `Position.vol` / `Position.avl_vol` / `Asset.cash` / `Asset.total_asset` 调回到 broker 真实值。下一次 `do_reconcile` 是几小时之后的兜底，期间 UI 与 broker 不一致。

3. **当日 / 历史耦合导致页面响应不一致**：现有 `client/src/views/Orders.vue` 和 `Trades.vue` 同时承载"前端持仓缓存中的当日数据 + 历史日期范围查询"。F5 后缓存丢失、`bootstrap` 拉的窗口固定为 30 天（`client/src/utils/trdDateFilter.js:BOOTSTRAP_WINDOW_DAYS`）。两者职责混在一个 view 里，导致 cancel-row 短路、trd_date 过滤、bootstrap 窗口三者叠加时视图逻辑冗余。

## Goals / Non-Goals

**Goals**：

- 删除 `Position.today_buy` / `Position.today_sell` 列及对应 spec 业务规则
- 引入资金 / 持仓**手动调平** API（不对应 delta 字段，而是直接对 `cash` / `total_asset` / `vol` / `avl_vol` 做原子 +/-，并打 `synced_from="manual"` 标记）
- 把"当日委托 / 当日成交"从混合查询视图剥离为独立路由 + 独立组件；数据从 `useHoldingsStore()` 内存读 + IDB 持久化（恢复被删除的 IDB write-through）
- 把"历史委托 / 历史成交"作为独立页面，**复用** `GET /api/orders` 与 `GET /api/trades` 现有 `start_date` / `end_date` / `stock_code` 参数（已在 `trading/spec.md:REQ-TRADE-001` 约定）
- 让 `bootstrap` 窗口的 30 天 bucket 与"当日"概念脱钩：`holdings.orders` / `holdings.trades` 仍负责启动期窗口拉取 + ws 推送增量，但 today 页面直接复用，前端不再混用 `trdDateFilter` 区间过滤

**Non-Goals**：

- 不重建 `Position` 表 `last_vol` / `avl_vol` 的算法（这俩仍由 `do_reconcile` 全量写入，盘中 trd_cfm 增量 vol 不动）
- 不动 `Asset.market_value` 的来源（仍由前端 `liveMarketValue` 实时算）
- 不改 push 链路（`trd_cfm` 增量 `Position.vol` 保留）
- 不引入 `AdjustAudit` 子表（用户明确"不留审计 row"）
- 不做后台自动调平（手动调平是 admin 一次性操作，不做调度器）

## Decisions

### D1 · 调整字段 = 直接原子加减，不存 delta 字段

**选择**：调平 API 对 `Position.vol` / `Position.avl_vol` 与 `Asset.cash` / `Asset.total_asset` 4 个总量字段做 `+=` 或 `-=`，**不**新增 `manual_offset_vol` / `manual_offset_cash` 列。

**理由**：
- 用户明确"直接提现到资金总量、资金可用 和 持仓总量、持仓可用上面" — 没有"offset 字段"的余地
- 不留 audit → 调整值不需要可追溯的累计语义，避免 state 漂移
- 下次 `do_reconcile` 会全表覆盖 — 调平只活在两次 reconcile 之间，本就是临时态

**取舍**：
- 优点：实现最简，不改 schema，UI 直接读现有字段即可显示
- 缺点：reconcile 一冲即无；多个 admin 同事同时调平互相覆盖无审计 — 但用户接受

**API 形态**：

```
PUT /api/positions/{stock_code}/adjust
  body: { delta_vol?: int, delta_avl_vol?: int, reason?: string }
  → Position.vol += delta_vol; Position.avl_vol += delta_avl_vol
  → synced_from = "manual"; synced_at = utcnow()

PUT /api/asset/adjust
  body: { delta_cash?: float, delta_total_asset?: float, reason?: string }
  → Asset.cash += delta_cash; Asset.total_asset += delta_total_asset
  → synced_from = "manual"; synced_at = utcnow()
```

注：`reason` 仅入 log，不入库（用户不要 audit row）。

### D2 · 删除 `Position.today_buy` / `Position.today_sell` 表列

**选择**：从 `server/models/orm.py:Position` 删除两列，同步 `data-model/spec.md` 表 3 字段表与对应业务规则段。

**理由**：用户明确"不需要 today_buy/sell 数据，前端也可以去掉"。删除一行 ALTER 比留两列加注释更彻底。

**取代方案**：
- 当日买入 / 卖出累计语义改由 `Trade` 表聚合（trd_cfm 落库 + ws 推送 + 前端 `applyTradePush` 已天然统计）— 无需新增字段
- `do_reconcile` 不再尝试写这两列（5.2 数据迁移脚本只清老数据，不写新数据）

**迁移**：
- ALTER TABLE `positions` DROP COLUMN `today_buy`, DROP COLUMN `today_sell`
- 历史 DB 中的值丢弃（保守起见如果想保留可建一份 `position_archive_today_buysell_{trd_date}.csv`，但用户没要求 audit）

### D3 · 当日 vs 历史拆分 + IDB 持久化恢复

**选择**：
- 新增 4 个 view 文件：`TodayOrders.vue` / `TodayTrades.vue` / `HistoryOrders.vue` / `HistoryTrades.vue`
- 保留 `OrderOut` / `TradeOut` Pydantic 不变；前端 API 调用仅拆方法
- 恢复 IDB write-through —— `client/src/stores/holdings_bootstrap.js:bootstrap` 后对 `holdings.orders` 和 `holdings.trades` 做 IDB 写，page reload 时序：
  1. Pinia mount（空 initial state）
  2. `bootstrap()` 触发：
     a. 读 `active_day`（`GET /api/system/active-day`）
     b. **若 IDB 存在 & IDB.trd_date === active_day.trd_date** → 立刻从 IDB 读回 orders / trades，UI 立即渲染当日数据
     c. 在 IDB 读回之后发起 ws.connect() 等待 push 增量
     d. **不**再发起 `/api/orders?trd_date=active_day` 的全量拉取（bootstrap 30 天窗口拉取逻辑保留用于 history 页面，但 today 页面只用 IDB）
     e. 当跨日（IDB.trd_date !== active_day.trd_date）时清 IDB + 走正常 bootstrap
- 新增 `client/src/stores/holdings_idb.js`：薄 IDB 包装，2 个 store（`orders_by_date` / `trades_by_date`），key = `trd_date`，value = `Array<OrderOut>` / `Array<TradeOut>`
- `client/src/utils/idb.js`（新）：打开 `EvTradeIDB` 数据库（schema version=1, `orders` / `trades` object stores，`stock_code` index 可选）

**权衡**：
- 与 `frontend/spec.md:REQ-FE-100` "无 IDB 持久化" 冲突：**这是 BREAKING**：本 change 引入 IDB write-through，**仅** orders / trades 两个 Pinia ref（positions 与 cachedAsset 仍然纯内存）
- `positions` / `cachedAsset` 留内存：这两者由 `GET /api/positions` + ws quote 增量计算实时市值，bootstrap 后即完整，不需跨 reload 保留

### D4 · 历史查询接口形态：复用现有 + 扩展参数

**选择**：`/api/orders` 与 `/api/trades` 早已支持 `start_date` / `end_date` / `stock_code`（`trading/spec.md:REQ-TRADE-001` 已写），前端 `HistoryOrders.vue` / `HistoryTrades.vue` 直接把这 3 个参数作为查询条件面板的输入。

**理由**：用户决策"复用现有端点，加 3 个 query 参数"。Spec 层面早已约定，实施层只缺前端正确传参。

**实施**：
- `client/src/api/index.js:getOrders / getTrades` 已经支持 `{ startDate, endDate, stockCode }` opts 入参（前端 `frontend/spec.md:REQ-FE-009.8` 已写），History 页面直接调
- date input：`<el-date-picker type="daterange">` + `stockCode` 输入框（可空）
- 提交时构造 opts，**必须**校验：`startDate <= endDate`（前端校验 + 后端 schema 校验）
- 响应分页：先用 0 分页（一次性返），数据量大的话改 cursor-based（不在本 change 范围）

### D5 · trd_cfm 增量 `Position.vol` 保留

**选择**：trd_cfm 同步增量 `Position.vol` 的语义（上一 change `consolidate-position-data-flow` 落地的）**保留不动**。

**理由**：
- 决策 1 用户选"保留 trd_cfm 增量"
- 删 `today_buy` / `today_sell` 不影响 vol 增量路径
- 与 day_init reconcile 全表覆盖 + 调平手工 +/- 共存：
  - 状态层级 = `reconcile 全量（开盘基准）` → `trd_cfm 增量（盘中实时）` → `manual adjust（盘中调平）`
  - `manual adjust` 直接修改当前值（已经包含 reconcile + trd_cfm 累计）
  - 不会"丢失"前两层（因为 `manual` 不是 delta 字段，不是叠加）

**风险**：
- 跨日 `trd_cfm` 还是按 `stock_code`（无 trd_date）改 vol — 历史遗留，**不在本 change 范围**，作为已知 issue 留在 `push/spec.md` § Known Issues

### D6 · 新增 spec 文件位置

| Spec 文件 | 性质 | 内容范围 |
|---|---|---|
| `specs/data-model/spec.md` | MODIFIED delta | 删 `Position.today_buy` / `today_sell`；删同步业务规则段 |
| `specs/positioning/spec.md` | MODIFIED delta | 删 `today_buy` / `today_sell` 相关 client 展示；加 manual adjust 客户端调用契约 |
| `specs/trading/spec.md` | MODIFIED delta | 加 `PUT /api/positions/{stock_code}/adjust` + `PUT /api/asset/adjust` 端点契约；加 `start_date` / `end_date` / `stock_code` 强调（REQ-TRADE-001 已写，重申为历史查询核心参数） |
| `specs/system-init/spec.md` | MODIFIED delta | day_init reconcile 全表覆盖语义 + manual adjust 不会入库后的特性边界 |
| `specs/frontend/spec.md` | MODIFIED delta | IDB write-through 重新启用（BREAKING REQ-FE-100）；today / history 页面拆分；`holdings_idb.js` 模块契约 |
| `specs/asset-position-adjust/spec.md` | NEW | manual adjust API 完整契约 |
| `specs/intraday-orders-trades-cache/spec.md` | NEW | IDB 持久化 + today 页面数据流契约 |
| `specs/orders-trades-history-query/spec.md` | NEW | history 页面数据流契约 |

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| **BREAKING**: 删除 `Position.today_buy` / `today_sell` 表列 | 已有 dev / prod DB schema | 写 Alembic-style 迁移脚本（dev 期 `rm evtrade.db` 重建，prod 提供 SQL 脚本）；前端确认无人读这俩字段（`grep -r "today_buy\|today_sell" client/src/` 应为 0） |
| **BREAKING**: IDB write-through 重新启用 | 与 `frontend/spec.md:REQ-FE-100` "无 IDB 持久化" 冲突 | REQ-FE-100 段补"已豁免：orders / trades 当日缓存走 IDB" |
| **manual adjust 调平窗口** | reconcile 后调平值被抹掉 | UI 上加 tooltip 提示"下次 day_init reconcile 会按柜台数据全表覆盖" |
| **多 admin 同时调平互相覆盖** | 调平无审计，最后一个写入者赢 | 用户明确接受"不留 audit row" |
| **trd_cfm 跨日** | 隔夜老委托 trd_cfm 仍按 stock_code 改 vol | 不是本 change 范畴；push/spec.md § Known Issues 已记录 |
| **History 页面无分页** | start_date/end_date 跨度大时返回数据量大 | 当下返回 Array<OrderOut>，前端 el-table pagination 可应付；数据量真的大（>5000 行/次）时再做 cursor-based |
| **IDB 写透失败** | IDB 写异常可能阻塞 ws push | IDB 写 try/catch + 不抛异常，失败打 warn log；push 链路不受影响 |
| **store 内存 vs IDB 数据漂移** | IDB 中 orders 比内存中陈旧 | ws push 同时改 Pinia 和 IDB；F5 后从 IDB 读回，立刻进 ws 增量补偿 |

## Migration Plan

### 数据迁移（一次性 dev 脚本）

```sql
-- dev 期
ALTER TABLE positions DROP COLUMN today_buy;
ALTER TABLE positions DROP COLUMN today_sell;

-- prod 期（保留 7 天回退窗口）
ALTER TABLE positions ADD COLUMN today_buy_temp INTEGER DEFAULT 0;
ALTER TABLE positions ADD COLUMN today_sell_temp INTEGER DEFAULT 0;
UPDATE positions SET today_buy_temp = today_buy, today_sell_temp = today_sell;
ALTER TABLE positions DROP COLUMN today_buy;
ALTER TABLE positions DROP COLUMN today_sell;
-- (回退：ALTER TABLE positions RENAME COLUMN today_buy_temp TO today_buy;)
```

### 实施分步（每步提交 + 测试可回退）

1. **phase 1 — 数据模型层**：删 Position 表列 + ORM 同步 + data-model spec delta 落地
2. **phase 2 — API 层**：新建 `PUT /api/positions/{stock_code}/adjust` + `PUT /api/asset/adjust` + 单元测试
3. **phase 3 — 前端 IDB 层**：引入 `holdings_idb.js` + bootstrap 加载 + 单元测试
4. **phase 4 — 前端页面拆分**：新建 `TodayOrders.vue` / `TodayTrades.vue` / `HistoryOrders.vue` / `HistoryTrades.vue` + 路由 + 旧 `Orders.vue` / `Trades.vue` 删除
5. **phase 5 — 联调 + spec 同步**：所有 spec delta 应用到主 spec + 测试覆盖 + archive

### 回滚

- phase 1：dev 期 `rm evtrade.db`；prod 期 ALTER COLUMN 回退脚本
- phase 2：路由 `register_adjust` 删除，5 分钟可回退
- phase 3：禁用 IDB 写（feature flag），保留模块待二次评估
- phase 4：路由改回旧 Orders.vue / Trades.vue 即可

## Open Questions

- **Q1**: IDB 写失败时 fallback？答：try/catch 不抛，warn 日志；ws push 不阻塞
- **Q2**: manual adjust 是否需要 broker 风控校验（防误调平过大金额）？答：本期不加，留 admin 自觉 + 下次 reconcile 兜底
- **Q3**: `TodayOrders.vue` 是否复用 `Trade.vue` 中的「今日委托」区？答：不复用 — Trade.vue 主体是下单 + T0 决策，「今日委托」会被 redirect 到 TodayOrders.vue（`router.replace`）
