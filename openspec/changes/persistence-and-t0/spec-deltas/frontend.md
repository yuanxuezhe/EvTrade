# Spec Delta — persistence-and-t0 → frontend

## ADDED Requirements

### REQ-FE-101: clock store 30s 轮询

- `client/src/stores/clock.js` Pinia store
- 字段：`tradingDay` / `initialized` / `isInSession` / `sessionWindow` / `currentTime`
- 方法：`refresh()` 调 `GET /api/trading/clock`
- 启动时调一次 + `setInterval(refresh, 30_000)`
- 暂停：标签页 hidden 时停止轮询

### REQ-FE-102: 守卫拦截 503

- `client/src/utils/guards.js`
- 拦截 `http.interceptors.response`
- 错误码：
  - `TRADING_DAY_NOT_INIT` → 跳 `/admin/trading-day`（admin 角色）/ 红条提示（非 admin）
  - `OUTSIDE_TRADING_SESSION` → ElMessage.warning，按钮置灰
  - `401` → 跳 `/login`（已有）

### REQ-FE-103: 按钮置灰

- `Trade.vue` 买入/卖出按钮：
  ```vue
  <el-button :disabled="!clock.isInSession || !clock.initialized">
  ```
- 鼠标 hover 显示原因（"非交易时段" / "请先做日初"）

### REQ-FE-104: 未初始化 banner

- 全局 `<TopBanner>` 组件
- 当 `!clock.initialized` 时显示：
  ```
  ⚠️ 未做日初处理，无法交易和查询
  [前往日初处理 →]
  ```

### REQ-FE-105: 日初处理页

- 路径：`/admin/trading-day`
- 角色：admin
- 功能：
  - 显示当前 trading_day 状态
  - 显示"开始日初处理"按钮 → 调 `POST /api/admin/trading-day/init`
  - 加载中显示对账进度（asset/positions/orders/trades）
  - 成功后显示 diff 报告
  - 失败时显示错误 + "重试"按钮
  - 对账历史列表（调 `GET /api/admin/reconcile/reports`）

### REQ-FE-106: 费率配置页

- 路径：`/settings`
- 角色：login
- 功能：
  - 显示当前 commission / stamp_tax / slippage
  - 编辑表单（数字输入 + 提示文案）
  - 保存调 `PATCH /api/settings/fee`
  - 成功后刷新 clock store

## MODIFIED Requirements

### REQ-FE-001（兼容保留）

- 现有路由保留
- 新增 `/settings` / `/admin/trading-day`
- `/trade` 顶部嵌入 `<T0Panel>` + 全局 `<TopBanner>`
