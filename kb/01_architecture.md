# 01 · 整体架构（Architecture）

## 1. 分层视图

```
┌────────────────────────────────────────────────────────────────────┐
│                          Browser (Vue 3 SPA)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │  Views   │──│ Pinia    │──│ api/     │──│ axios    │            │
│  │ (路由页) │  │ Stores   │  │ index.js │  │ http     │            │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │
│       ▲             ▲             │              │                 │
│       └─────────────┴─────────────┼──────────────┘                 │
│                                   │  HTTP (Bearer JWT)             │
└───────────────────────────────────┼────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────┐
│                       FastAPI Gateway (server/)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ api/*    │──│ auth/    │──│ db.py    │──│ services/│            │
│  │ routers  │  │ deps     │  │ SQLAlch  │  │ trading  │            │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │
│       ▲                                              │              │
│       │                                              ▼              │
│  ┌──────────┐                                ┌──────────┐           │
│  │ ws/      │                                │ rpc/     │           │
│  │ manager  │                                │ client   │           │
│  └──────────┘                                └──────────┘           │
└───────────────────────────────────┬──────────────┬──────────────────┘
                                    │              │
                          ┌─────────▼─────┐  ┌─────▼──────────┐
                          │  RabbitMQ     │  │  XtQuant       │
                          │  msgpacket    │  │  (迅投QMT)     │
                          │  exchange     │  │  本地客户端     │
                          └───────┬───────┘  └────────────────┘
                                  │
                          ┌───────▼────────┐
                          │  模拟柜台 /     │
                          │  其他 RPC 服务  │
                          └────────────────┘
```

## 2. 模块依赖图

### 2.1 前端模块
```
main.js
  └─ App.vue
       ├─ Sidebar.vue          (uiStore + orderStore)
       ├─ AppHeader.vue        (uiStore + assetStore + orderStore + positionStore + authStore)
       └─ <router-view>        (懒加载 9 个 views)
            ├─ Login.vue
            ├─ Dashboard.vue
            ├─ Position.vue     → PositionTable.vue + PositionDetail.vue
            ├─ Trade.vue        → OrderForm.vue + OrderStatusBadge.vue
            ├─ Asset.vue
            ├─ Orders.vue       → OrderStatusBadge.vue
            ├─ Trades.vue
            ├─ Users.vue
            └─ Profile.vue      → ChangePasswordDialog.vue
```

### 2.2 后端模块
```
main.py
  ├─ db.py  (Base, SessionLocal, get_db, init_db)
  ├─ models/user.py  (User ORM, Base.metadata.create_all)
  ├─ auth/security.py  (hash_password, verify_password, create_access_token, decode_token)
  ├─ auth/deps.py  (get_current_user, require_admin, require_trader)
  └─ api/
       ├─ auth.py        (POST /api/auth/login, GET /api/auth/me, ...)
       ├─ asset.py       (GET /api/asset)
       ├─ positions.py   (GET /api/positions, POST /api/positions/{code}/init)
       ├─ orders.py      (GET /api/orders, POST /api/orders, POST /api/orders/place, DELETE /api/orders/{id})
       ├─ trades.py      (GET /api/trades)
       └─ users.py       (admin only CRUD)
             └─ 调用 services/trading.py 内存仓库 或 rpc/client.py
                  └─ rpc/client.py 通过 aio_pika 连 RabbitMQ → 柜台
```

## 3. 请求时序

### 3.1 鉴权 + 查询
```
[Browser] GET /api/asset
   │
   ▼
[FastAPI] Depends(get_current_user) → 校验 Bearer JWT
   │
   ▼
[asset.py] get_account_asset()
   │
   ▼
[rpc/client.py] qry_asset()
   │  1. 检查/创建 RPClient (singleton)
   │  2. await client.call("qry_ast")
   │  3. 构造 MsgPacket (REQUEST) + msg_id
   │  4. publish 到 exchange (routing_key=EvTrade.Test.Req)
   │  5. await future（按 msg_id 匹配应答）
   │  6. _parse_asset() 解包 → dict
   │
   ▼
[Browser] res.data → assetStore.asset
```

### 3.2 下单（fire-and-forget）
```
[Browser] POST /api/orders/place
   │
   ▼
[orders.py] place_order()  [require_trader]
   │
   ▼
[rpc/client.py] ord_stk()
   │  1. 构造 MsgPacket (func=ord_stk, headers=5, row=...)
   │  2. publish → 不等 future
   │  3. return { order_id: msg_id[:8], status: "pending" }
   │
   ▼
[Browser] 显示"已提交"（实际成交通知会通过 Push 队列）
```

## 4. 数据契约（接口 ↔ 客户端 store）

| API 字段 | 前端 store | 类型 | 说明 |
|----------|-----------|------|------|
| `/api/asset` → `{cash, frozen_cash, market_value, total_asset}` | `useAssetStore.asset` | ref<number×4> | 资金快照 |
| `/api/positions` → `[{stock_code, stock_name, initial_position, today_buy, today_sell, available, total}]` | `usePositionStore.positions` | ref<array> | 持仓列表 |
| `/api/orders` → `[{order_id, stock_code, direction, volume, price, price_type, status, traded_volume, traded_price, order_time}]` | `useOrderStore.orders` | ref<array> | 委托列表 |
| `/api/trades` → `[{trade_id, order_id, stock_code, direction, volume, price, trade_time}]` | `useOrderStore.trades` | ref<array> | 成交列表 |
| `/api/auth/me` → `{id, username, email, full_name, role, is_active, created_at, last_login_at}` | `useAuthStore.user` | ref<object> | 当前用户 |
| `/api/users` → `[{id, username, email, full_name, role, is_active, ...}]` | `Users.vue` 本地 | ref<array> | 用户列表 |

## 5. 鉴权流

```
登录成功 → token 存 localStorage
        → axios 拦截器自动加 Authorization
        → 后端 Depends(get_current_user) 校验 JWT
        → 401 → 拦截器清 token + 路由跳 /login?redirect=...

角色守卫：
  require_admin   → admin
  require_trader  → admin | trader
  (无 dep)        → 任何已登录用户
```

详见 `server/02_auth.md` 与 `cross/03_role_matrix.md`。

## 6. 状态机：订单 12 态

XtQuant 11 档状态码 + 前端兼容 `pending`：

```
unreported → pending_report → reported → partial
                                       ↘ reported_cancel → cancelled
                                       ↘ partial_pending_cancel → partial_cancelled
                                       ↘ filled
                                       ↘ rejected
                                                       ↘ cancelled
```

完整映射见 `cross/02_order_status.md`。

## 7. 关键运行参数

| 参数 | 位置 | 默认值 |
|------|------|--------|
| Vite dev port | `client/vite.config.js` | 3000 |
| FastAPI port | 启动命令 | 8000 |
| CORS origin | `server/main.py` | http://localhost:3000 |
| JWT 有效期 | `server/auth/security.py` | 24h |
| bcrypt rounds | `server/auth/security.py` | 12 |
| AXIOS timeout | `client/src/api/index.js` | 15000ms |
| RPC future timeout | `server/rpc/client.py` | 30s |
| 路由 `requiresAdmin` | `client/src/router/index.js` | /users |
| 路由 `requiresTrader` | `client/src/router/index.js` | /trade |
| 订单自动刷新周期 | `Trade.vue` | 5s |

## 8. 扩展点

| 扩展方向 | 涉及文件 | 提示 |
|----------|----------|------|
| 新增页面 | `client/src/views/` + `client/src/router/index.js` | 注意 `meta.requiresAdmin/Trader` |
| 新增接口 | `server/api/*.py` + `server/main.py` 注册 | 注意依赖注入 `_AUTH` |
| 新增角色 | `models/user.py` 默认值 + `auth/deps.py` 守卫 + `client/src/router` meta | 三处同步 |
| 接入真实柜台 | 改写 `server/services/xtquant.py` 或新增适配器 | 保持 `trading.py` 接口 |
| 启用 WebSocket | `server/main.py` 挂载 `ws` 路由 + 前端 `api.createWSConnection` | 通道名对应 `manager.py` |
