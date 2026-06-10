# Client · 02 · Pinia 状态管理（Stores）

> 5 个 store：`auth` / `asset` / `order` / `position` / `ui`
> 风格：Composition API `defineStore(id, () => { ... })`

## 1. `useAuthStore` —— 鉴权

文件：`client/src/stores/auth.js`

### 1.1 状态
| 字段 | 类型 | 来源 |
|------|------|------|
| `token` | ref\<string> | `localStorage.evtrade-token` |
| `user` | ref\<object\|null> | `localStorage.evtrade-user` |
| `loading` | ref\<boolean> | 登录按钮 loading |

### 1.2 计算属性
| 名称 | 条件 |
|------|------|
| `isAuthenticated` | `!!token && !!user` |
| `isAdmin` | `user.role === 'admin'` |
| `isTrader` | `user.role === 'admin' \|\| 'trader'` |
| `isViewer` | `user.role === 'viewer'` |

### 1.3 方法
| 方法 | 行为 | 用到的 API |
|------|------|-----------|
| `login(u, p)` | 调 `authApi.login`，存 token + user | POST /api/auth/login |
| `fetchMe()` | 调 `authApi.me`，存 user；失败 clear | GET /api/auth/me |
| `logout()` | 调 `authApi.logout`（忽略失败），clear | POST /api/auth/logout |
| `clear()` | 重置 token + user + 清 localStorage | — |
| `updateProfile(p)` | 调 `authApi.updateProfile` 并 saveUser | PATCH /api/auth/me |
| `changePassword(old, new)` | 调 `authApi.changePassword` | POST /api/auth/change-password |

### 1.4 持久化
- `token` → `localStorage.evtrade-token`
- `user` → `localStorage.evtrade-user`（JSON）

### 1.5 启动恢复
`App.vue onMounted`：
```js
if (authStore.token && !authStore.user) await authStore.fetchMe()
```

## 2. `useAssetStore` —— 资金

文件：`client/src/stores/asset.js`

### 2.1 状态
```js
asset = ref({ cash: 0, frozen_cash: 0, market_value: 0, total_asset: 0 })
loading = ref(false)
```

### 2.2 方法
`fetchAsset()`：GET /api/asset → 写入 `asset`（数值 `Number()` 强转）。异常仅 `console.error`。

### 2.3 典型消费者
- `Dashboard.vue`（KPI 卡 + 资产饼图）
- `Asset.vue`（hero 区 + 4 张详情卡 + 饼图）
- `AppHeader.vue`（总资产 mini chip）

## 3. `useOrderStore` —— 委托 + 成交

文件：`client/src/stores/order.js`

### 3.1 状态
```js
orders = ref([])
trades = ref([])
```

### 3.2 方法
| 方法 | 入参 | 调用 | 副作用 |
|------|------|------|--------|
| `fetchOrders(stockCode?)` | 股票过滤 | GET /api/orders | 覆盖 `orders` |
| `fetchTrades(stockCode?)` | 股票过滤 | GET /api/trades | 覆盖 `trades` |
| `createOrder(data)` | OrderCreate | POST /api/orders | 追加到 `orders` |
| `placeOrder(data)` | OrderCreate | POST /api/orders/place | 仅返回新订单，不入 store（轮询刷新） |
| `cancelOrder(orderId)` | 委托号 | DELETE /api/orders/{id} | 本地 `order.status = 'cancelled'` |

### 3.3 轮询策略
`Trade.vue` 中 `setInterval(fetchOrders, 5000)`，组件卸载时 clear。
其它视图（`Orders.vue`）仅在手动点击"刷新"时拉取。

## 4. `usePositionStore` —— 持仓

文件：`client/src/stores/position.js`

### 4.1 状态
```js
positions = ref([])
selectedStockCode = ref(null)
```

### 4.2 计算属性
`selectedPosition` = 在 `positions` 中按 `stock_code` 找到的项

### 4.3 方法
| 方法 | 行为 |
|------|------|
| `fetchPositions()` | GET /api/positions → 覆盖 `positions` |
| `initPosition(stockCode)` | POST /api/positions/{code}/init → 重新 fetchPositions |
| `selectStock(stockCode)` | 设置 `selectedStockCode`，触发 `PositionDetail` 抽屉 |

## 5. `useUiStore` —— UI 偏好

文件：`client/src/stores/ui.js`

### 5.1 状态
| 字段 | 类型 | 默认 | 持久化 |
|------|------|------|--------|
| `sidebarCollapsed` | ref\<bool> | `localStorage.evtrade-sidebar === '1'` | ✅ |
| `theme` | ref\<'light'\|'dark'> | `localStorage.evtrade-theme \|\| 'light'` | ✅ |
| `lastRefreshAt` | ref\<Date\|null> | — | ❌ |

### 5.2 方法
| 方法 | 行为 |
|------|------|
| `toggleSidebar()` | 翻转并写 localStorage |
| `toggleTheme()` | 切换 'light' / 'dark'，apply |
| `applyTheme()` | 在 `<html>` 上 add/remove `.dark`，写 localStorage |
| `markRefreshed()` | 设置 `lastRefreshAt = new Date()` |

### 5.3 副作用
- 初始化时 `applyTheme()` 同步一次
- `watch(theme, applyTheme)` 自动持久化

### 5.4 全局影响
- `App.vue` 用 `uiStore.sidebarCollapsed` 切换 grid 列宽
- `main.js` 启动时直接读 `localStorage.evtrade-theme` 加 `.dark`
- 多个组件按 `uiStore.theme` 切换 ECharts 主题

## 6. 跨 store 调用关系

```
AppHeader.handleRefresh
   ├─ assetStore.fetchAsset()
   ├─ orderStore.fetchOrders()
   ├─ orderStore.fetchTrades()
   └─ positionStore.fetchPositions()
       └─ uiStore.markRefreshed()

Dashboard.onMounted
   ├─ assetStore.fetchAsset()
   ├─ orderStore.fetchOrders()
   ├─ orderStore.fetchTrades()
   └─ positionStore.fetchPositions()

Position.handleSelect(stockCode)
   ├─ positionStore.selectStock(stockCode)
   ├─ orderStore.fetchOrders(stockCode)
   └─ orderStore.fetchTrades(stockCode)
```

## 7. 与 `api/index.js` 的关系

stores **不直接 fetch**，全部走 `api` / `authApi` / `userApi` 聚合模块。改动 store 的请求行为时，需同时改 `api/index.js`。
