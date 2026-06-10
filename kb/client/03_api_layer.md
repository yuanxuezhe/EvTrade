# Client · 03 · API 层（axios 封装 + 业务聚合）

> 文件：`client/src/api/index.js`

## 1. 模块导出总览

```js
export const http              // axios 实例
export const tokenStorage      // localStorage 工具
export const setUnauthorizedHandler(fn)  // 注册 401 回调
export const api               // 业务 API（持仓/委托/成交/资金）
export const authApi           // 鉴权 API
export const userApi           // 用户管理 API
export function createWSConnection(channel)  // WebSocket 占位
```

## 2. axios 实例

### 2.1 配置
```js
http = axios.create({
  baseURL: '/api',
  timeout: 15000
})
```

### 2.2 请求拦截器
```js
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('evtrade-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
```

### 2.3 响应拦截器
```js
let onUnauthorized = null
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('evtrade-token')
      if (onUnauthorized) onUnauthorized()
    }
    return Promise.reject(err)
  }
)
```

> 401 处理器由 `client/src/router/index.js` 注册，用于跳转登录页。

## 3. Token 工具

```js
export const tokenStorage = {
  get:   () => localStorage.getItem('evtrade-token'),
  set:   (t) => localStorage.setItem('evtrade-token', t),
  clear: () => localStorage.removeItem('evtrade-token')
}
```

## 4. 业务 API（`api`）

| 方法 | HTTP | 路径 | 入参 | 出参 |
|------|------|------|------|------|
| `getPositions()` | GET | `/positions` | — | `Position[]` |
| `initPosition(stockCode)` | POST | `/positions/{stockCode}/init` | path | `Position` |
| `getOrders(stockCode?)` | GET | `/orders` | `params.stock_code` | `Order[]` |
| `createOrder(data)` | POST | `/orders` | `OrderCreate` | `Order` |
| `placeOrder(data)` | POST | `/orders/place` | `OrderCreate` | `Order` |
| `cancelOrder(orderId)` | DELETE | `/orders/{orderId}` | path | `{order_id, status}` |
| `getTrades(stockCode?)` | GET | `/trades` | `params.stock_code` | `Trade[]` |
| `getAsset()` | GET | `/asset` | — | `Asset` |

## 5. 鉴权 API（`authApi`）

| 方法 | HTTP | 路径 | 特殊处理 |
|------|------|------|----------|
| `login(username, password)` | POST | `/auth/login` | 使用 `URLSearchParams` 转 form-urlencoded |
| `me()` | GET | `/auth/me` | — |
| `updateProfile(payload)` | PATCH | `/auth/me` | `{email?, full_name?}` |
| `changePassword(old, new)` | POST | `/auth/change-password` | `{old_password, new_password}` |
| `logout()` | POST | `/auth/logout` | try/catch 吞错 |

> 登录用 `application/x-www-form-urlencoded` 因为后端是 `OAuth2PasswordRequestForm`。

## 6. 用户管理 API（`userApi`）

| 方法 | HTTP | 路径 | 入参 |
|------|------|------|------|
| `list({keyword, role})` | GET | `/users` | query |
| `create(payload)` | POST | `/users` | `UserCreateRequest` |
| `update(id, payload)` | PATCH | `/users/{id}` | `UserUpdateRequest` |
| `resetPassword(id, newPassword)` | POST | `/users/{id}/reset-password` | `{new_password}` |
| `delete(id)` | DELETE | `/users/{id}` | path |

## 7. WebSocket 占位

```js
export function createWSConnection(channel = 'order_update') {
  const wsUrl = `ws://${window.location.host}/ws/${channel}`
  const ws = { value: null }
  const messages = []
  let connected = false

  function connect() {
    ws.value = new WebSocket(wsUrl)
    ws.value.onopen   = () => { connected = true }
    ws.value.onmessage = (e) => { messages.push(JSON.parse(e.data)) }
    ws.value.onclose  = () => { connected = false }
  }
  // ...
  return { ws, messages, connected, disconnect }
}
```

> 当前**未被任何视图调用**。一旦后端 `main.py` 挂载 `/ws/{channel}`，即可在 stores / views 中接入。

## 8. 错误处理约定

| 场景 | 表现 | 处理方 |
|------|------|--------|
| 401 | 拦截器清 token + 触发 onUnauthorized | 路由层跳 /login |
| 400 | `e.response.data.detail` | UI 弹 `ElMessage.error(detail)` |
| 500 | `str(e)` | 同上 |
| 网络异常 | `e.message` | 同上 |
| 业务"静默" | `qry_asset` / `qry_positions` 失败返回全 0 / `[]` | 视图显示空态 |

## 9. Vite 代理（`vite.config.js`）

```js
server: {
  port: 3000,
  proxy: {
    '/api': { target: 'http://localhost:8000', changeOrigin: true },
    '/ws':  { target: 'ws://localhost:8000',   ws: true }
  }
}
```
- 浏览器发到 `/api/*` → 转发到 FastAPI
- 浏览器发到 `/ws/*` → 转发到 WebSocket（同源）
