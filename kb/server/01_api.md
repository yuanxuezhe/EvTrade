# Server · 01 · API 接口清单

> 所有路由前缀 `/api`，注册位置：`server/main.py`。
> 鉴权模型详见 `server/02_auth.md`。

## 路由总览

| 模块 | 路径前缀 | 鉴权 | 源文件 |
|------|----------|------|--------|
| 鉴权 | `/api/auth` | 公开（除 logout） | `server/api/auth.py` |
| 持仓 | `/api/positions` | 已登录 | `server/api/positions.py` |
| 委托 | `/api/orders` | 已登录（下单/撤单需 trader） | `server/api/orders.py` |
| 成交 | `/api/trades` | 已登录 | `server/api/trades.py` |
| 资金 | `/api/asset` | 已登录 | `server/api/asset.py` |
| 用户管理 | `/api/users` | admin | `server/api/users.py` |
| 健康检查 | `/api/health` | 公开 | `server/main.py` |

注册代码：
```python
app.include_router(auth_api.router,   prefix="/api/auth",      tags=["auth"])
app.include_router(positions.router,  prefix="/api/positions", tags=["positions"], dependencies=_AUTH)
app.include_router(orders.router,     prefix="/api/orders",    tags=["orders"],    dependencies=_AUTH)
app.include_router(trades.router,     prefix="/api/trades",    tags=["trades"],    dependencies=_AUTH)
app.include_router(asset.router,      prefix="/api/asset",     tags=["asset"],     dependencies=_AUTH)
app.include_router(users_api.router,  prefix="/api/users",     tags=["users"])
```

> 注：`/api/users` 路由内部按方法挂 `require_admin` 依赖，不是路由级。

---

## 1. 鉴权 `/api/auth`

源文件：`server/api/auth.py` · 公开路由

### 1.1 `POST /api/auth/login`
- 入参：`OAuth2PasswordRequestForm`（`application/x-www-form-urlencoded`）
  - `username: str` (form)
  - `password: str` (form)
- 出参：`TokenResponse`
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 86400,
    "user": { "id":1, "username":"admin", "role":"admin", ... }
  }
  ```
- 行为：
  1. bcrypt 校验密码
  2. 检查 `is_active`
  3. 写入 `user.last_login_at = utcnow()` 并 commit
  4. 签发 JWT，payload `{ sub: str(user.id), role: user.role, iat, exp }`
- 错误：
  - `401 用户名或密码错误`
  - `403 账号已禁用`

### 1.2 `GET /api/auth/me`
- 鉴权：必填
- 出参：`UserInfoResponse`（`id, username, email, full_name, role, is_active, created_at, last_login_at`）
- 错误：
  - `401 未登录或登录已过期`
  - `401 无效或过期的令牌`
  - `401 令牌缺少用户标识`
  - `401 用户不存在`
  - `403 账号已禁用`

### 1.3 `PATCH /api/auth/me`
- 鉴权：必填
- 入参：`UpdateProfileRequest { email?: str, full_name?: str }`
  - 空字符串会被规范化为 `null`
- 出参：`UserInfoResponse`
- 行为：仅更新非空字段，commit 后刷新

### 1.4 `POST /api/auth/change-password`
- 鉴权：必填
- 入参：`ChangePasswordRequest { old_password: str, new_password: str }`
- 行为：bcrypt 校验旧密码 → 校验新密码长度 ≥ 6 → 校验新旧不同 → 重写 hash
- 错误：
  - `400 原密码错误`
  - `400 新密码长度需至少 6 位`
  - `400 新密码不能与原密码相同`

### 1.5 `POST /api/auth/logout`
- 鉴权：必填（保留审计位）
- 出参：`{ success: true }`
- 说明：JWT 无状态，前端直接丢弃 token；服务端仅做语义占位

---

## 2. 持仓 `/api/positions`

源文件：`server/api/positions.py` · 已登录

### 2.1 `GET /api/positions`
- 鉴权：已登录
- 出参：`List<PositionResponse>`
  ```json
  [
    {
      "stock_code": "000001.SZ",
      "stock_name": "平安银行",
      "initial_position": 1000,
      "today_buy": 200,
      "today_sell": 100,
      "available": 1100,
      "total": 1100
    }
  ]
  ```
- 行为：调用 `rpc.client.qry_positions()` 异步 RPC；异常时返回 `[]`

### 2.2 `POST /api/positions/{stock_code}/init`
- 鉴权：require_trader
- 路径参数：`stock_code`
- 出参：`PositionResponse` 或 `{"error": "position not found"}`
- 行为：调用 `services.trading.init_position(stock_code)`
  - 把当前 `total` 写为新的 `initial_position`
  - 重置 `today_buy = 0`、`today_sell = 0`

---

## 3. 委托 `/api/orders`

源文件：`server/api/orders.py` · 已登录（部分需 trader）

### 3.1 `GET /api/orders`
- 鉴权：已登录
- Query：
  - `stock_code?: str`（按股票过滤）
  - `use_rpc?: bool = true`
- 出参：`List<OrderResponse>`
  ```json
  [
    {
      "order_id": "8a3c1b0e",
      "stock_code": "000001.SZ",
      "direction": "BUY",
      "volume": 100,
      "price": 11.12,
      "price_type": "LIMIT",
      "status": "filled",
      "traded_volume": 100,
      "traded_price": 11.10,
      "order_time": "09:35:21"
    }
  ]
  ```
- 行为：
  - `use_rpc=True`：调 `qry_orders()`，对 XtQuant 状态码调用 `_map_status()` 映射为前端 key
  - `use_rpc=False`：回退到 `services.trading.get_orders()` 内存仓库
- 错误：RPC 异常时返回 `[]`

### 3.2 `POST /api/orders`
- 鉴权：require_trader
- 入参：`OrderCreate { stock_code, direction, volume, price, price_type="LIMIT" }`
- 行为：**仅写入内存**（不发送到柜台），用于本地测试
- 出参：`OrderResponse`，`status="pending"`

### 3.3 `POST /api/orders/place`
- 鉴权：require_trader
- 入参：`OrderCreate`
- 行为：调用 `rpc.client.ord_stk()` fire-and-forget 发送 RabbitMQ 报文
- 出参：`OrderResponse`
  - `order_id = msg_id[:8]`（临时单号，需通过 GET /api/orders 轮询真实状态）
  - `status = "pending"`
- 错误：`500` + `detail=str(e)`

### 3.4 `DELETE /api/orders/{order_id}`
- 鉴权：require_trader
- 路径参数：`order_id`
- 行为：调用 `services.trading.update_order_status(order_id, "cancelled")`
- 出参：`{ "order_id": "...", "status": "cancelled" }`

### 3.5 状态码映射 `_map_status`
| XtQuant | 数值 | 前端 key |
|---------|------|----------|
| ORDER_UNREPORTED | 48 | `unreported` |
| ORDER_WAIT_REPORTING | 49 | `pending_report` |
| ORDER_REPORTED | 50 | `reported` |
| ORDER_REPORTED_CANCEL | 51 | `reported_cancel` |
| ORDER_PARTSUCC_CANCEL | 52 | `partial_pending_cancel` |
| ORDER_PART_CANCEL | 53 | `partial_cancelled` |
| ORDER_CANCELED | 54 | `cancelled` |
| ORDER_PART_SUCC | 55 | `partial` |
| ORDER_SUCCEEDED | 56 | `filled` |
| ORDER_JUNK | 57 | `rejected` |
| ORDER_UNKNOWN | 255 | `unknown` |

详见 `cross/02_order_status.md`。

---

## 4. 成交 `/api/trades`

源文件：`server/api/trades.py` · 已登录

### 4.1 `GET /api/trades`
- 鉴权：已登录
- Query：
  - `stock_code?: str`
- 出参：`List<TradeResponse>`
  ```json
  [
    {
      "trade_id": "T202606090001",
      "order_id": "8a3c1b0e",
      "stock_code": "000001.SZ",
      "direction": "BUY",
      "volume": 100,
      "price": 11.10,
      "trade_time": "09:35:25"
    }
  ]
  ```
- 行为：调用 `services.trading.get_trades(stock_code)`，**未走 RPC**（从内存仓库）

---

## 5. 资金 `/api/asset`

源文件：`server/api/asset.py` · 已登录

### 5.1 `GET /api/asset`
- 鉴权：已登录
- 出参：`AssetResponse`
  ```json
  {
    "cash": 100000.50,
    "frozen_cash": 5000.00,
    "market_value": 80000.00,
    "total_asset": 185000.50
  }
  ```
- 行为：调用 `rpc.client.qry_asset()`；任何异常时返回全 0（**不抛错**）

---

## 6. 用户管理 `/api/users`

源文件：`server/api/users.py` · 所有方法均 require_admin

### 6.1 角色枚举
`VALID_ROLES = {"admin", "trader", "viewer"}`
`USERNAME_RE = ^[A-Za-z0-9_\-\.]{3,32}$`

### 6.2 `GET /api/users`
- 鉴权：require_admin
- Query：
  - `keyword?: str`（匹配 username / email / full_name，ilike）
  - `role?: str`
- 出参：`List<UserResponse>`，按 `id asc` 排序

### 6.3 `POST /api/users`
- 鉴权：require_admin
- 入参：`UserCreateRequest { username, password, role="trader", email?, full_name?, is_active=true }`
- 校验：
  - 用户名格式
  - 密码 ≥ 6 位
  - role 必须在 `VALID_ROLES`
  - 用户名唯一
- 错误：
  - `400 用户名需3-32位字母/数字/_/-/.`
  - `400 密码长度至少 6 位`
  - `400 角色必须是 ...之一`
  - `409 用户名已存在`
- 出参：`UserResponse`（201）

### 6.4 `PATCH /api/users/{user_id}`
- 鉴权：require_admin
- 入参：`UserUpdateRequest { role?, email?, full_name?, is_active? }`
- 业务规则：
  - 最后一个 admin 不能被降级
  - 不能禁用自己
  - 最后一个启用的 admin 不能被禁用
- 错误：
  - `404 用户不存在`
  - `400 必须至少保留一个管理员`
  - `400 不能禁用当前登录账号`
  - `400 必须至少保留一个启用的管理员`
- 出参：`UserResponse`

### 6.5 `POST /api/users/{user_id}/reset-password`
- 鉴权：require_admin
- 入参：`PasswordResetRequest { new_password: str }`
- 校验：密码 ≥ 6 位
- 错误：`404 / 400`
- 出参：`{ success: true, message: "密码已重置" }`

### 6.6 `DELETE /api/users/{user_id}`
- 鉴权：require_admin
- 业务规则：
  - 不能删除自己
  - 最后一个 admin 不能删除
- 错误：`400 / 404`
- 出参：`{ success: true }`

### 6.7 `UserResponse` 字段
```json
{
  "id": 1, "username": "admin",
  "email": null, "full_name": "系统管理员",
  "role": "admin", "is_active": true,
  "created_at": "2026-06-09T08:00:00",
  "updated_at": "2026-06-09T08:00:00",
  "last_login_at": "2026-06-09T09:00:00"
}
```

---

## 7. 健康检查

### 7.1 `GET /api/health`
- 鉴权：公开
- 出参：`{ "status": "ok" }`
