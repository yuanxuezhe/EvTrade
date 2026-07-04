## Why

Trade 页面右侧的 mini-panel (今日委托 / 今日成交) 在内容短时下方留白, 顶部多一个低频使用的"刷新"按钮, 且不内嵌分页导致交易员在百笔以上的活跃日需要反复滚动查看; 委托 / 成交查询作为独立路由 (TodayOrders / TodayTrades) 与 Trade.vue 内嵌 panel 形成**重复入口**, 而且 HistoryOrders / HistoryTrades 缺少按昨日/最近三天/一周/一个月预设查询的快捷面板, 用户重复键入日期范围效率低。

本变更把"今日数据 = Trade.vue 内嵌 panel + 缓存直读" 与 "历史数据 = 独立路由 + 后端区间查询" 严格分层:
- Trade.vue 移除低价值 quicklinks, 让左右两列等分整屏高度 (不再留白)
- Mini-panel 加 el-pagination (20 行/页) 让委托 / 成交量大的活跃日也能在 panel 内翻页
- 删除冗余的 TodayOrders.vue / TodayTrades.vue 视图, 把 `/orders` `/trades` 改指向 history 路由 (sidebar 改名 + 删 pending badge)
- HistoryOrders / HistoryTrades 加 4 个 chip (昨日 / 3 天 / 周 / 月), 点击即查 (auto-trigger runQuery)
- History view 强制 "dateRange 不含今日" (历史语义), datepicker 设上限 today-1
- 撤单权限收紧: 只有 mini-panel (数据范围 = 今日委托) 才出现撤单按钮, HistoryOrders 永远没有 (架构已满足, 仅补 spec 锁)

## What Changes

- **Trade.vue 顶部 .trade-quicklinks 删除** (`委托查询` 与 `成交查询` 链接 + 刷新按钮整行移除)
- **Trade.vue 左列整屏填充**: `.trade-form-col > *` 加 `flex: 1 1 0; min-height: 0` 让 OrderForm + QuotePanel 等分左列高度
- **TodayOrdersPanel / TodayTradesPanel 加 el-pagination**: 20 行/页 (pageSizes `[10,20,50,100]`), dataSource 改为 `pagedOrders` / `pagedTrades` computed
- **TodayOrdersPanel / TodayTradesPanel 精简**: 移除 refresh 图标按钮, 移除滚动进度条 + ResizeObserver
- **删除 views/TodayOrders.vue 与 views/TodayTrades.vue** (无任何其它 view 引用, 已 grep 验证)
- **router/index.js**: `/orders` redirect → `/history/orders`, `/trades` redirect → `/history/trades`; 新增 `/today/orders` `/today/trades` redirect → `/history/*` 作为老书签兼容; 移除 `import TodayOrders` / `import TodayTrades`
- **Sidebar.vue**: `委托查询` → `历史委托`, `成交查询` → `历史成交`; 删除 `pendingCount` computed + badge (依赖老本地 status 码 pre-existing bug, 借此清掉)
- **HistoryOrders.vue / HistoryTrades.vue**: filter-bar 加 4 个 chip 按钮 (昨日 / 最近三天 / 最近一周 / 最近一个月) — `昨日=[today-1,today-1]`, `最近三天=[today-3,today-1]`, `最近一周=[today-7,today-1]`, `最近一个月=[today-30,today-1]`; 点击即 `runQuery()`
- **HistoryOrders.vue / HistoryTrades.vue**: el-date-picker 设 `:disabled-date` 禁选 today/today+ (强制历史); onMounted 改成 `dateRange=null` (不默认查今日, 用户主动选); picker 范围 = 预设范围时对应 chip 自动高亮 (双向联动)
- **BREAKING**: 移除 `/today/orders` `/today/trades` 路由; sidebar 移除 pending badge (用户视觉提示减弱, 由 AppHeader 的 pending badge + ws push 实时反映兜底)

## Capabilities

### New Capabilities

- (无 — 仅修改现有 capability)

### Modified Capabilities

- `frontend`: REQ-FE-001 路由表删除 `/today/*` 行, `/orders` `/trades` redirect 目标从 `/today/*` 改为 `/history/*`; 加新 REQ: Trade.vue panel 不含顶部 quicklinks, 左列 flex 链整屏填充, mini-panel 内嵌分页 (20 行/页); 加新 REQ: 撤单权限范围 (只有今日委托才有撤单按钮)
- `orders-trades-history-query`: 加 REQ 预设日期 chip (昨日/3 天/周/月, 自动触发查询); 加 REQ history view dateRange 不含今日 (datepicker 禁 today+, onMounted 不默认今日); 加 REQ chip ↔ picker 双向联动高亮; REMOVED 默认查询激活日 scenario (改为留空)
- `intraday-orders-trades-cache`: REMOVED 今日委托/今日成交 view (`TodayOrders.vue` / `TodayTrades.vue`) 要求; ADDED 今日面板组件 (`TodayOrdersPanel.vue` / `TodayTradesPanel.vue` 在 Trade.vue 内嵌), 数据源/IDB 双写契约不变

## Impact

**受影响的代码 (`client/src/`):**
- `views/Trade.vue` — 删 quicklinks 行, 加左列 flex, 删 Refresh import + refreshAll 函数 + refreshing ref
- `views/TodayOrders.vue` — **删除**
- `views/TodayTrades.vue` — **删除**
- `views/HistoryOrders.vue` — 加 4 chip + `setPresetRange()` helper, picker `disabled-date`, onMounted 改留空, chip ↔ picker 高亮联动
- `views/HistoryTrades.vue` — 同 HistoryOrders 改动
- `components/trade/TodayOrdersPanel.vue` — 加 el-pagination, 删 refresh 按钮 + ResizeObserver + scroll listener
- `components/trade/TodayTradesPanel.vue` — 同 TodayOrdersPanel (无撤单按钮)
- `components/Sidebar.vue` — label 改名, 删 `pendingCount` badge + 关联 import
- `router/index.js` — 改 redirect 目标, 删 2 import, 加 2 兼容 redirect

**不受影响:**
- `client/src/stores/holdings*.js` — `BOOTSTRAP_WINDOW_DAYS=1` 已保证 bootstrap 仅拉单日, mini-panel 客户端再做 `trd_date === activeDay` 守门即可 (架构已满足"今日缓存 = 后端 start/end = activeDay"约束); ws push 通道 (applyOrderPush / applyTradePush) 不动
- `client/src/api/index.js` — `getOrders` / `getTrades` 已支持 `{startDate, endDate}` opts, History view 直接复用
- `client/src/views/Dashboard.vue` 等 21 个业务 view — 不动
- 后端 — 不动 (FastAPI 端点 `start_date/end_date` 区间过滤已支持)

**潜在风险:**
1. `pendingCount` badge 删除后, 持仓面板的"待成交"提示减弱 — 缓解: AppHeader 已有总持仓 badge; pending 状态通过 ws push 实时反映 (`applyOrderPush` → orders.value[idx] status 变化 → `<OrderStatusBadge>` 自动更新)
2. History view onMounted 改留空, 首屏空白可能被用户视为"页面坏了" — 缓解: el-empty 文案明确"请选择日期区间查询"; 4 chip 是首选入口; 先在用户第一次打开时给出明确引导
3. 老用户书签 `/today/orders` 失效 — 缓解: router 加 `/today/orders` → `/history/orders` redirect 保兼容
4. chip 的今天排除 (`最近三天 = today-3 ~ today-1`, 不含 today) 可能让用户误以为"最近一周"包含今天 — 缓解: chip 文案明确 (例如 "最近 3 天 (历史)" / 加 tooltip)
