# frontend — Vue3 前端

## Purpose

单页应用，12 个视图，WebSocket 实时更新，JWT 鉴权。
部署在 Windows dev 环境，监听 :50998。

## Requirements

### REQ-FE-001: 路由

| 路径 | 视图 | 鉴权 |
|---|---|---|
| `/login` | Login.vue | public |
| `/` | Dashboard.vue | login |
| `/trade` | Trade.vue | trader |
| `/orders` | Orders.vue | login |
| `/trades` | Trades.vue | login |
| `/positions` | → redirect `/to-management` | login |
| `/to-management` | Position.vue（快速做T） | login |
| `/t-strategy` | TStrategy.vue（策略做T） | login |
| `/algo-strategy` | AlgoStrategy.vue | login |
| `/holdings` | Holdings.vue | login |
| `/asset` | Asset.vue | login |
| `/users` | Users.vue | admin |
| `/profile` | Profile.vue | login |

### REQ-FE-002: API 客户端

- 入口 `client/src/api/index.js` 导出 axios 实例
- 拦截器：401 → 清 token + 跳 `/login`
- 拦截器：RPC 响应统一处理 — `code≠0` 时弹 ElMessage.error + reject
- 拦截器自动把 `{code, msg, list}` 展平为 `list` 数组

### REQ-FE-003: Pinia stores

| Store | 职责 | 数据源 |
|---|---|---|
| `auth` | JWT、用户信息、角色 | `/api/auth/*` |
| `ui` | 通用 UI 状态（侧栏折叠等） | localStorage |
| `order` | 委托列表 | `/api/orders` + WS `order_update` |
| `position` | 持仓 | `/api/positions` |
| `asset` | 资金 | `/api/asset` |
| `holdings` | 持仓聚合视图（含资金/委托/成交/持仓） | 批量 `/api/...` |
| `quote` | 行情订阅列表 | WS `quote_update` |
| `ws` | WebSocket 连接管理 | — |

### REQ-FE-004: WebSocket

- 业务频道（`order_update` 等）连 `ws://<host>:8000/ws/<channel>`
- 行情频道（`quote_update`）连 `ws://<host>:8765`（hqserver）

### REQ-FE-005: UI 偏好（来自 user memory）

- 固定条默认折叠为单行
- 折叠态不显示标题
- 背景实心不透明
- 不重复按钮
- 流水按标签 `check-tag` 筛选

## Scenarios

### S-FE-001: 未登录访问 `/orders`

When 浏览器请求 `/orders`  
Then router.beforeEach 检测到无 token → 重定向 `/login?redirect=/orders`  
And 登录成功后跳回 `/orders`

### S-FE-002: viewer 访问 `/trade`

When viewer 角色访问 `/trade`  
Then router 检测到 `requiresTrader` 不满足 → 重定向 `/`

### S-FE-003: 行情实时推送

When QMT 推一条 `600030.SH|...|12.34|...` 到 RabbitMQ  
Then hqserver WS 推 `{"channel":"quote_update","data":{...}}`  
And 前端 `quote` store 更新对应 stock_code 的 last_price  
And Asset/Holdings 等视图若订阅了该股则自动刷新

## Known Issues (from analysis)

- 🟡 `TStrategy.vue` / `AlgoStrategy.vue` 各 43 行，**未实现内容**
- 🟡 `auth.js` store 应该在 401 时自动清 token + 跳 login，目前**依赖** axios 拦截器调用 `setUnauthorizedHandler`
- 🟢 UI 偏好已沉淀到 user memory，UI 改动前先查
