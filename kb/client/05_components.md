# Client · 05 · 通用组件（Components）

> 11 个组件，按职责分组。

## 1. 布局 / 导航

### 1.1 `AppHeader.vue`
- 顶部 header：左标题（按 `route.path` 查 `pageMeta`）、中市值 mini chip、右交易状态 + 时间 + 主题切换 + 用户下拉
- `handleRefresh` 并行拉取 `asset/orders/trades/positions`
- `handleUserCmd`：profile / users / password / logout
- `logout` 前 `ElMessageBox.confirm` 确认

### 1.2 `Sidebar.vue`
- 左侧导航，根据 `uiStore.sidebarCollapsed` 切换宽窄
- 菜单数据 `menuItems`（computed）：
  - 基底：Dashboard / Position / Trade / Orders / Trades / Asset
  - `pendingCount` > 0 → 委托查询菜单加 badge
  - admin 追加 Users（带 divider）
- `isActive(path)` 精确匹配 `/`，其它用 `startsWith`

### 1.3 `NavBar.vue`（**遗留**，未被 App.vue 引用）
- 仅一个 `el-menu` 横向导航 5 项
- 当前未使用，建议删除或改造

## 2. 业务组件

### 2.1 `OrderForm.vue`
- Props: `onSubmit: Function`, `defaultStockCode: String`
- 表单字段：`stock_code / direction(BUY|SELL) / price_type(LIMIT|LATEST|FAIR) / price / volume`
- 快捷：价格（涨停 +1% / -1% / 跌停）、数量（100/500/1k/5k/1w）
- 预估金额 + 预估手续费（`max(5, amount*0.00025)`）
- 提交前 `ElMessageBox.confirm` 显示确认弹窗
- 提交后 `handleReset()`，把 price 归 0、volume 归 100
- 输入校验：股票代码必填、限价时价格 > 0、数量 > 0

### 2.2 `PositionTable.vue`
- Props: `positions: Array, loading: Bool, selected: String`
- Emits: `select(stockCode)`
- 列：# / stock_code / 期初 / 今日买 / 今日卖 / 可用 / 总持仓 / 可用占比（进度条）/ 操作
- 行点击触发 `select` 事件
- 选中行加 `.row-selected` 类（背景色）

### 2.3 `PositionDetail.vue`
- Props: `orders, trades, position, stockCode`
- 两个 summary card：做T收益 / 需买回股数
- 持仓信息：期初/今日买/今日卖/可用/总持仓
- Tabs：时间线 / 表格
- `profit` 计算：
  - `buyVolume = min(today_buy, today_sell)`
  - `avgBuy / avgSell = sum / qty`
  - `profit = (avgSell - avgBuy) * buyVolume`
- `needBuyBack = max(0, initial_position - total)`

### 2.4 `OrderStatusBadge.vue`
- Props: `status, size ('sm'|'md')`
- 从 `utils/format.js` 读 5 张映射表
- CSS 类组合：`.tone-pending/.tone-working/.tone-done/.tone-terminal` + `.pulse`
- 图标 + 文字 + 圆点（pulse 时有阴影扩散动画）

### 2.5 `ChangePasswordDialog.vue`
- v-model 绑定
- 三字段：old_password / new_password / confirm
- 校验：new ≥ 6 位，confirm == new
- 提交成功 → 提示 → 800ms 后自动 logout + 跳 /login

## 3. 展示组件

### 3.1 `StatCard.vue`
- Props: `label, value, prefix, sublabel, trend, icon, accent, clickable, formatter`
- accent：`primary` / `up` / `down` / `warning` / `info`
- 内置 6 图标映射：`Wallet / Money / DataAnalysis / TrendCharts / Box / PieChart`
- `trend > 0` 向上、`< 0` 向下、`= 0` 横线
- 背景装饰圆（按 accent 着色）

### 3.2 `EChart.vue`
- 按需引入 LineChart / BarChart / PieChart + Title/Tooltip/Grid/Legend/DataZoom
- Props: `option: Object, height: String = '320px'`
- `watch(option, ...)` 自动 `setOption`
- `watch(uiStore.theme, init)` 主题切换时重新初始化（dark/light）
- `onUnmounted` 释放实例

## 4. 用户管理对话框（在 `Users.vue` 内联）
`Users.vue` 直接内联了两个 el-dialog：
- 新建/编辑用户
- 重置密码
> 没有抽成独立组件（保持简洁）。

## 5. 组件使用清单

| 组件 | 使用方 |
|------|--------|
| `AppHeader` | `App.vue` |
| `Sidebar` | `App.vue` |
| `OrderForm` | `Trade.vue` |
| `PositionTable` | `Position.vue` |
| `PositionDetail` | `Position.vue`（抽屉内） |
| `OrderStatusBadge` | `Dashboard.vue` / `Trade.vue` / `Orders.vue` / `PositionDetail.vue` |
| `ChangePasswordDialog` | `AppHeader.vue` / `Profile.vue` |
| `StatCard` | `Dashboard.vue` |
| `EChart` | `Dashboard.vue` / `Asset.vue` |
| `NavBar` | （未使用） |

## 6. 主题与样式

- CSS 变量集中在 `client/src/assets/styles/main.css`（含 `--bg-base / --text-primary / --brand-gradient` 等）
- 暗色主题通过 `<html class="dark">` 切换
- 多数组件使用 `var(--xxx)` 引用，全局切肤
