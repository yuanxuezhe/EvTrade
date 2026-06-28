# EvTrade 项目分析报告

> 探查日期：基于当前 git 工作区
> 工作目录：`/root/workspcae/codespace/EvTrade`（注意 `workspace` 拼写为 `workspcae`）
> 报告定位：项目结构、技术栈、业务流程、数据模型、待办事项全景

---

## 一、项目概览

### 1.1 项目定位
**EvTrade** 是一个基于 Web 的 **A 股智能交易终端**（桌面级 GUI 风格），对接券商 QMT（迅投 MiniQMT / iQuant）交易柜台，把 XtQuant 本地 Python SDK 的能力通过 **FastAPI + msgpacket RPC** 暴露成 REST + WebSocket 标准化服务，再由 Vue 3 前端以类"同花顺 / 东方财富"风格的界面呈现给最终用户。

### 1.2 目标用户
- **系统管理员（admin）**：账号、用户、权限、系统设置管理
- **交易员（trader）**：实盘下单、撤单、查询资产/持仓/委托/成交
- **只读用户（viewer）**：仅查询，不允许下单/撤单/写操作

### 1.3 核心场景
1. **登录鉴权** — JWT 24h 有效，bcrypt 散列存储，三角色权限
2. **快速下单** — 限价 / 最新价 / 挂单价 / 市价 四档，支持 ±1%、±10% 快捷键
3. **资产/持仓/委托/成交** 实时查询
4. **Dashboard 仪表盘** — ECharts 资产曲线、收益概览
5. **持仓管理（TO管理）** 与 **期初持仓（holdings）** 两类持仓视图
6. **策略交易菜单**（UI 已有） — 快速做T / 策略做T / 策略交易 / 日内策略 / 算法策略（后端尚未实现）

---

## 二、技术栈

| 层 | 选型 | 关键依赖 |
|---|---|---|
| **前端框架** | Vue 3 (Composition API) | `vue@3` + `vue-router` + `pinia` |
| **UI 库** | Element Plus | `@element-plus/icons-vue` |
| **可视化** | ECharts | `echarts`（Dashboard.vue 引入） |
| **HTTP 客户端** | Axios | 拦截器统一处理 token / 错误 |
| **构建工具** | Vite | 端口 3000，代理 `/api` `/ws` → 8002 |
| **后端框架** | FastAPI | `fastapi` + `uvicorn` |
| **ORM** | SQLAlchemy 1.4 | `sqlalchemy`，SQLite 默认 |
| **认证** | python-jose + passlib | `python-jose[cryptography]` JWT HS256，`bcrypt` rounds=12 |
| **异步 RPC** | aio-pika | RabbitMQ MsgPacket 协议封装 |
| **柜台 SDK** | xtquant | iQuant / MiniQMT 本地 SDK（仅 Windows） |
| **消息中间件** | RabbitMQ | `amqp://192.168.10.2:5672/`，exchange `msgpacket.exchange` |
| **WS 推送** | FastAPI WebSocket | 原生 `fastapi.WebSocket`，未挂载到路由 |
| **数据库** | SQLite | 默认本地文件，init_db 自动建表 |

---

## 三、系统架构

```
┌────────────────┐   HTTP/HTTPS   ┌────────────────┐
│   浏览器       │ ─────────────► │  Vue 3 SPA     │
│ (Element Plus) │ ◄───────────── │  + ECharts     │
│  localStorage  │   WS /api/ws   │  Vite :3000    │
└────────────────┘                └────────┬───────┘
                                          │ Vite Proxy
                                          ▼
                                ┌────────────────────┐
                                │  FastAPI 后端      │
                                │  REST  /api/*      │
                                │  JWT + RBAC        │
                                │  + WS  (未挂载)    │
                                │  :8002             │
                                └─────┬──────┬───────┘
                                      │      │
                       直接 in-proc   │      │  aio-pika (异步 RPC)
                                      │      ▼
                                      │  ┌────────────────────┐
                                      │  │  RabbitMQ Broker   │
                                      │  │  msgpacket.exchange│
                                      │  │  ─ EvTrade.Test.Req│
                                      │  │  ─ EvTrade.Test.Rpl│
                                      │  │  ─ EvTrade.Test.Psh│
                                      │  └─────────┬──────────┘
                                      │            │ MsgPacket wire
                                      ▼            ▼
                          ┌──────────────────────────────┐
                          │  iQuant / MiniQMT 柜台       │
                          │  Windows 进程                │
                          │  XtQuant SDK (Python)        │
                          │  ── 账户/资产/委托/成交 ──  │
                          │  ── 回报推送 (Push queue)── │
                          └──────────────────────────────┘
```

**关键路径说明**：
- **当前实际链路**：`xtquant.py`（`get_asset`）走本地直连 SDK；`qry_*` 与 `ord_stk` 走 RabbitMQ 异步 RPC。
- **KB 描述**：msgpacket RPC 方案为主，**与代码现状存在不一致**（见第十二节"待办"）。
- **WebSocket**：WSManager 已实现但未挂载到 FastAPI 路由；前端 `stores/ws.js` 已写好客户端但仅在 `Dashboard` 占位调用。

---

## 四、后端模块结构

### 4.1 入口与配置

| 文件 | 职责 |
|---|---|
| `server/main.py` | FastAPI app 工厂；`on_startup` 中 seed admin 账号（`count==0` 触发）；注册 6 个 router |
| `server/config.py` | 加载 `EVTRADE_*` 环境变量，默认端口 8002 |
| `server/db.py` | SQLAlchemy `Base` / `SessionLocal` / `get_db` / `init_db`（自动建表） |
| `server/.env.example` | 配置模板（已含敏感值占位） |
| `server/.env` / `.env.sc` | **实际配置（含凭证，本次未读取）** |
| `server/2.0` | **误提交文件** — 实际是 pip install 输出日志，非代码（2.7KB） |
| `server/test_rpc.py` | RPC 联通测试脚本（730B，标准库 + aio-pika） |

### 4.2 API 路由（`server/api/`）

| 端点文件 | 路径前缀 | 鉴权要求 | 端点摘要 |
|---|---|---|---|
| `auth.py` | `/api/auth` | 公开+JWT | `POST /login`、`GET /me`、`PUT /me`、`PUT /password`、`POST /logout` |
| `users.py` | `/api/users` | **admin** | 用户 CRUD：`GET /`（分页）、`POST /`、`GET /{id}`、`PUT /{id}`（含 admin 保护）、`DELETE /{id}` |
| `orders.py` | `/api/orders` | **trader/admin** | `POST /`（下单）、`DELETE /{id}`（撤单）、`GET /`（列表 + 筛选）、`GET /{id}` |
| `trades.py` | `/api/trades` | JWT | `GET /`（成交流水） |
| `positions.py` | `/api/positions` | JWT | `GET /`、`POST /init`（期初持仓初始化） |
| `asset.py` | `/api/asset` | JWT | `GET /`（资产） |
| `holdings.py` | `/api/holdings` | JWT | `GET /`（期初持仓 / TO管理；最后 commit: `feat(holdings): last_vol 替代股票名称`） |

### 4.3 服务层（`server/services/`）

| 文件 | 职责 | 备注 |
|---|---|---|
| `xtquant.py` | **本地 XtQuant 适配**（直连 SDK） | 含硬编码 `TRADE_PATH = r'D:\software\trade\iQuant\userdata'` 与 `ACCOUNT_ID = '410001265100'`；`init_trader()` / `get_asset()` / `qry_*` 封装 |
| `trading.py` | 内存级领域服务（Position/Order/Trade/Asset 仓库） | 进程内 dataclass 单例，未持久化 |

### 4.4 RPC 层（`server/rpc/`）

| 文件 | 职责 |
|---|---|
| `client.py`（501–601 行） | aio-pika 异步 RPC 客户端；`RpcClient` 单例 + `ord_stk()` + `qry_asset()` / `qry_position()` / `qry_order()` / `qry_trade()` + `_parse_*` 字段映射 |

**RPC 封装要点**：
- 三个队列 `EvTrade.Test.{Req,Reply,Push}`，topic exchange `msgpacket.exchange`
- 默认超时 30s
- 与柜台字段通过 `_parse_*` 工具方法映射（如 `order_type` 数字 ↔ 字符串、`price_type` 柜台数字 → 11/5/14/44）
- **未实现 Push 消费者**

### 4.5 数据模型（`server/models/`）

| 文件 | 内容 |
|---|---|
| `user.py` | `User` ORM（id, username, email, full_name, role, is_active, password_hash, created_at, updated_at） |
| `types.py` | **dataclass** 内存模型：`Position` / `Order` / `Trade` / `Asset` |
| `__init__.py` | （未读取） |

### 4.6 鉴权（`server/auth/`）

| 文件 | 职责 |
|---|---|
| `security.py` | bcrypt 散列 + JWT 编解码；密钥三优先级：`EVTRADE_SECRET` env > `server/auth/.secret_key` 文件 > 自动生成 `secrets.token_urlsafe(64)` |
| `deps.py` | FastAPI 依赖：`oauth2_scheme` / `get_current_user` / `require_admin` / `require_trader` |
| `__init__.py` | **空文件（0 字节）** |

### 4.7 WebSocket（`server/ws/`）

| 文件 | 职责 |
|---|---|
| `manager.py` | `WSManager` 单例，4 通道（`order_update` / `trade_update` / `position_update` / `asset_update`），提供 `connect / disconnect / broadcast` 方法 |

**注意**：WS 路由**未挂载**到 FastAPI app。

---

## 五、前端模块结构

### 5.1 应用骨架

| 文件 | 职责 |
|---|---|
| `client/src/main.js` | Vue 3 启动 + Element Plus 全量注册 + Pinia |
| `client/src/router/index.js` | 9 条路由 + 守卫（admin/trader 限定） |
| `client/src/api/index.js` | Axios 封装：`request` / `authApi` / `userApi` / `orderApi` / `tradeApi` / `positionApi` / `assetApi` / `holdingsApi` / `wsApi` + `tokenStorage` |
| `client/vite.config.js`（推测） | Vite 端口 3000，代理 `/api` + `/ws` → `http://localhost:8002` |

### 5.2 路由（`router/index.js`）

| 路径 | 组件 | 守卫 |
|---|---|---|
| `/login` | `Login.vue` | 公开 |
| `/` | `Layout.vue` | 需登录 |
| `/dashboard` | `Dashboard.vue` | 需登录 |
| `/trade` | `Trade.vue` | trader 或 admin |
| `/orders` | `Orders.vue` | 需登录 |
| `/position` | `Position.vue` | 需登录 |
| `/holdings` | `Holdings.vue`（新） | 需登录 |
| `/users` | `Users.vue` | **admin** |
| `/profile` | `Profile.vue` | 需登录 |

### 5.3 视图（`views/`）

| 文件 | 关键内容 |
|---|---|
| `Dashboard.vue`（17KB） | 资产总览、ECharts 曲线、收益概览、账户统计 |
| `Trade.vue`（11KB） | 下单页，集成 `OrderForm.vue`；订单状态每 5s 轮询 `GET /api/orders` |
| `Orders.vue`（13KB） | 委托列表，支持筛选 / 撤单 |
| `Position.vue`（8.5KB） | 持仓列表 + `PositionDetail.vue`（含盈亏计算） |
| `Holdings.vue`（新） | 期初持仓视图，6 字段（commit: `b9c22e4`） |
| `Login.vue` / `Layout.vue` / `Users.vue` / `Profile.vue` / `Asset.vue` | 标准页面（未全部详读） |

### 5.4 组件（`components/`）

| 文件 | 职责 |
|---|---|
| `OrderForm.vue`（8.7KB） | 完整下单表单：方向 Tab / 股票代码 / 价格类型 4 档 / 委托价 / 委托数 / 快捷键 / 预估金额 / 手续费估算 / 二次确认弹窗 |
| `PositionTable.vue` | 持仓表格 |
| `PositionDetail.vue` | 持仓详情 + 盈亏 |

### 5.5 状态管理（`stores/`）

| 文件 | 内容 |
|---|---|
| `auth.js`（2.1KB） | token + user + `isAdmin` / `isTrader` / `isViewer` 计算属性；`login` / `logout` / `fetchMe` / `changePassword` / `updateProfile` |
| `order.js`（1.5KB） | 订单列表状态 |
| `position.js`（821B） | 持仓列表 + 选中股票 |
| `asset.js`（854B） | 资产数据（cash / frozen_cash / market_value / total_asset） |
| `ws.js`（9.5KB） | WS 客户端封装：含重连 / 心跳 / 4 通道订阅；**当前仅 Dashboard 占位调用** |

**localStorage keys**：
- `evtrade-token`（token 存储）
- `evtrade-user`（用户对象 JSON）
- `evtrade-remember-username`（记住用户名）
- `evtrade-theme` / `evtrade-sidebar`（UI 偏好）

---

## 六、核心业务流程

### 6.1 用户登录 / 鉴权

```
用户输入用户名/密码
   ↓
POST /api/auth/login  (application/x-www-form-urlencoded, OAuth2PasswordRequestForm)
   ↓
auth.py: 校验 bcrypt → User.is_active=True
   ↓
创建 JWT（HS256，sub=user.id, exp=24h）
   ↓
返回 { access_token, token_type: "bearer", user: {...} }
   ↓
前端：tokenStorage.set + saveUser + Pinia auth store
   ↓
后续请求：Axios 拦截器附加 Authorization: Bearer <token>
   ↓
后端 deps.get_current_user 解码 → 校验 is_active → 返回 User 对象
   ↓
require_admin / require_trader 进一步限制
```

**关键设计**：
- 路由守卫在前端 `router/index.js`，API 守卫在后端 `auth/deps.py`，**双重保险**
- 退出登录时 `fetchMe` 失败会触发 `clear()`，避免 stale token
- 改密后旧 token 仍可用（**未实现 token 黑名单/失效机制**）

### 6.2 下单流程

```
Trade.vue → OrderForm.vue
   ↓ 用户点击「确认买入/卖出」
ElMessageBox 二次确认
   ↓
POST /api/orders  { stock_code, order_type, price_type, price, volume }
   ↓
auth/deps.require_trader 校验
   ↓
orders.py 构造 MsgPacket 请求
   ↓
rpc/client.py.ord_stk()
   ↓ publish 到 EvTrade.Test.Req
   ↓ 等 reply（30s timeout）
柜台 XtQuant 接收 → 同步/异步回报
   ↓ reply
RpcClient 解析 → 返回 { order_id (临时), status: "submitted" }
   ↓
后端 orders.py 返回 OrderResponse（Pydantic）
   ↓
前端：ElMessage 提示成功 → reset 表单
```

**⚠️ 关键现状**：
1. **真实回报走 Push 队列** `EvTrade.Test.Push`，但**消费者未实现**——前端只能通过 5s 轮询 `GET /api/orders` 拿到状态更新
2. `ord_stk` 是 fire-and-forget，返回的是**临时 ID**，真实柜台回报单号需要 Push 消费端落地后才能绑定

### 6.3 持仓 / 资产 / 委托 / 成交 查询流程

```
前端任意视图
   ↓
GET /api/positions（或 /asset /orders /trades /holdings）
   ↓
auth/deps.get_current_user 鉴权
   ↓
api/*.py 解析 query params → 构造 MsgPacket qry_* 请求
   ↓
rpc/client.py.qry_position() / qry_asset() / qry_order() / qry_trade()
   ↓ RabbitMQ Req → Reply
柜台 XtQuant 查询
   ↓ reply (多结果集 MsgPacket)
RpcClient._parse_*() 字段映射
   ↓ 返回 Pydantic list
后端 API 返回 JSON
   ↓
前端：Pinia store 更新 → 视图响应式刷新
```

**例外**：`get_asset` 走 `xtquant.py` 本地直连（已实现且可用），其他查询走 RPC。

---

## 七、数据模型

### 7.1 User（SQLAlchemy ORM）
| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | Integer | PK, autoincrement |
| `username` | String(64) | unique, not null, `^[A-Za-z0-9_\-\.]{3,32}$` |
| `email` | String(120) | nullable |
| `full_name` | String(80) | nullable |
| `role` | String(16) | enum: `admin` / `trader` / `viewer` |
| `is_active` | Boolean | default True |
| `password_hash` | String(128) | bcrypt rounds=12 |
| `created_at` | DateTime | default utcnow |
| `updated_at` | DateTime | onupdate utcnow |

### 7.2 内存 dataclass（`server/models/types.py`）
| 类型 | 字段（推测） |
|---|---|
| `Position` | stock_code, stock_name, volume, available, frozen, cost_price, market_value, profit, profit_ratio |
| `Order` | order_id, stock_code, order_type (23/24), price_type (11/5/14/44), price, volume, filled_volume, status, created_at |
| `Trade` | trade_id, order_id, stock_code, price, volume, trade_time, commission |
| `Asset` | cash, frozen_cash, market_value, total_asset |

> ⚠️ `types.py` 仅声明 dataclass，**未与 SQLAlchemy User 关联**，所有交易数据走内存 + 柜台实时查询，不持久化。

### 7.3 消息契约（MsgPacket）
- `OrderCreate`：stock_code, order_type, price_type, price, volume, account_id
- `OrderResponse`：order_id, status, error_code, error_msg
- `AssetQuery` / `PositionQuery` / `OrderQuery` / `TradeQuery`：含分页 / 筛选
- wire 格式：`magic[4]='YSWY' + crc32[4] LE + body_len[4] LE + header(72B) + body`，总长 `83 + body_len`；转义 `0x1B` 转 `0x1F/0x1E/0x1C/0x1B/0x1D`

---

## 八、API 端点清单

### 8.1 认证 `/api/auth`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/login` | 公开 | OAuth2 表单登录，返回 token + user |
| GET | `/me` | JWT | 当前用户信息 |
| PUT | `/me` | JWT | 更新个人资料（email / full_name） |
| PUT | `/password` | JWT | 改密（验证旧密码） |
| POST | `/logout` | JWT | 登出（前端清 token，**后端无黑名单**） |

### 8.2 用户管理 `/api/users`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | **admin** | 分页查询（skip/limit/search/role/is_active） |
| POST | `/` | **admin** | 创建用户 |
| GET | `/{id}` | **admin** | 用户详情 |
| PUT | `/{id}` | **admin** | 更新用户（含 admin 保护：最后一个 admin 不可降级/禁用/删除；不能操作自己） |
| DELETE | `/{id}` | **admin** | 删除用户（同上保护） |

### 8.3 订单 `/api/orders`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/` | trader | 下单（rpc.ord_stk） |
| GET | `/` | JWT | 委托列表（支持 stock_code / status / date 筛选） |
| GET | `/{id}` | JWT | 委托详情 |
| DELETE | `/{id}` | trader | 撤单 |

### 8.4 成交 `/api/trades`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | JWT | 成交流水（支持日期/股票/订单号筛选） |

### 8.5 持仓 `/api/positions`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | JWT | 当前持仓 |
| POST | `/init` | trader | 期初持仓初始化（按股票） |

### 8.6 资产 `/api/asset`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | JWT | 账户资产 |

### 8.7 期初持仓 `/api/holdings`
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | JWT | 期初持仓视图（last_vol 替代股票名称，6 字段） |

---

## 九、关键设计决策

### 9.1 msgpacket 选型原因（推测）
- **解耦**：后端 Python 与柜台 iQuant（可能 C++/C#）通过标准化二进制协议通信，不依赖平台 / 语言
- **异步非阻塞**：aio-pika 协程模型，下单/查询并发性能好
- **可观测性**：通过 RabbitMQ Topic 路由，多队列（Req/Reply/Push）解耦请求-响应与推送
- **容错**：30s RPC 超时、reply correlation_id 匹配

### 9.2 WebSocket 推送机制
- **设计意图**：下单/成交/持仓/资产变化通过 `EvTrade.Test.Push` 队列消费 → `WSManager.broadcast` → 前端 `stores/ws.js` 接收 → Pinia 更新
- **当前状态**：
  - ✅ `WSManager` 实现完整（4 通道）
  - ✅ 前端 `stores/ws.js` 实现完整（含重连 / 心跳）
  - ❌ **WS 路由未挂载**（`main.py` 缺 `@app.websocket("/ws/{channel}")`）
  - ❌ **Push 消费者未实现**
  - ❌ **前端 Dashboard 之外未调用 WS**
  - **降级方案**：Trade.vue / Orders.vue 用 5s 轮询

### 9.3 角色权限矩阵（已落地）

| 角色 | 登录 | 查资产/持仓/委托/成交 | 下单/撤单 | 期初持仓 init | 用户管理 |
|---|---|---|---|---|---|
| admin | ✅ | ✅ | ✅ | ✅ | ✅ |
| trader | ✅ | ✅ | ✅ | ✅ | ❌ |
| viewer | ✅ | ✅ | ❌ | ❌ | ❌ |

**硬约束**：
- 最后一个 admin 不可降级/禁用/删除
- 不能禁用/删除自己
- 改密需提供旧密码
- 用户名 `^[A-Za-z0-9_\-\.]{3,32}$`，密码 ≥ 6 位

### 9.4 端口与配置硬约束
- **后端端口 8002**：8000 / 8001 被占用，已通过 `EVTRADE_API_PORT=8002` 调整
- **前端端口 3000**
- **Vite 代理**：`/api` + `/ws` → `http://localhost:8002`，改端口需同步 `scripts/dev.ps1` 与 `client/vite.config.js`

### 9.5 数据契约双轨
- **内存 dataclass**（`models/types.py`）：本地计算、临时状态
- **RPC MsgPacket 结果集**：柜台通信二进制协议
- **Pydantic**（API 层）：前后端 JSON 契约
- 三层转换由 `_parse_*` 工具方法集中处理

---

## 十、与 msgpacket 项目的关系

### 10.1 项目结构关系
- **EvTrade** 是 msgpacket 协议的**客户端**（FastAPI 后端）
- **iQuant / MiniQMT** 是 msgpacket 协议的**服务端**（柜台）
- 通信介质：RabbitMQ（解耦、可观测）

### 10.2 `iquant/xtquant_api.py`（参考实现）
- 9KB，**GBK 编码**，部分中文注释乱码
- 完整本地 XtQuant SDK 用法示例：连接 miniQMT、订阅报价、查询资产/持仓/委托/成交、下单、撤单
- 供 EvTrade 团队理解柜台能力

### 10.3 `iquant/demo_rpc_client.py`（参考实现）
- 5.9KB，RabbitMQ 三队列客户端示例（Req/Reply/Push）
- 演示如何 publish / consume MsgPacket 消息
- **价格类型约定**与项目代码不一致：demo 用 `"0"` 等裸数字字符串，项目用 `'LIMIT' / 'LATEST' / 'FAIR'`

### 10.4 `iquant/demo_builder.py`（参考实现）
- 7.8KB，MsgPacket 多结果集打包示例（`addRow` / `addField` / `build`）

### 10.5 落地策略
- `server/rpc/client.py` 直接使用 aio-pika，**未复用** demo 中的 MsgPacket 编解码工具
- `server/services/xtquant.py` 走本地 SDK，**绕开** msgpacket 协议
- **两条路并行**，是技术债务（见第十二节）

---

## 十一、当前状态评估

### 11.1 Git 提交历史（最近 30 次）

```
0789072 feat(holdings): 期初持仓 last_vol 替代股票名称
df5d0dc feat(sidebar): 策略交易下平铺 3 项
fc4ca52 feat(sidebar): 新增策略交易分组
b9c22e4 feat: 持仓查询改为展示 RPC 6 个原始字段
cbb6b4d feat(sidebar): 添加持仓查询菜单项
30fb775 feat(router): 注册 /holdings 路由
e12576a feat: 新建持仓查询视图 Holdings.vue
aafa75a docs: 持仓查询实施计划
7dcb6d2 docs: 持仓查询页面设计方案
cf9db70 优化程序
48956c4 修正重启脚本
5a7cd1c commit
696790d feat: add navigation bar and layout
a94647c feat: Asset page view
9403547 feat: Trade page view
df8522b feat: Position page view
3bbb7bc feat: OrderForm component
176b351 feat: PositionDetail component with profit calculation
9722242 feat: PositionTable component
b350bc9 feat: frontend Pinia stores
fad2049 feat: frontend API layer and router
0ec8dfd feat: WebSocket implementation
52dc549 feat: orders, trades, asset API implementation
a0ee0a2 feat: positions API implementation
33013be feat: project scaffold - initial files and data models
```

### 11.2 完成度评估

| 模块 | 完成度 | 备注 |
|---|---|---|
| **后端 API 骨架** | 90% | 7 个 router 全部注册；admin 保护完整 |
| **JWT 鉴权** | 95% | 登录/改密/角色守卫完整；缺 token 黑名单 |
| **下单链路** | 70% | RPC 调用完成，**缺 Push 消费者** → 真实回报丢失 |
| **查询链路** | 80% | `get_asset` 走本地直连 OK；其他 RPC 字段映射需验证 |
| **WebSocket** | 30% | WSManager + 客户端完成，**未挂载路由**，**未对接 Push 队列** |
| **前端 UI** | 85% | 9 个路由 + 核心视图 + OrderForm 完整；Dashboard ECharts 集成 |
| **权限矩阵** | 100% | 路由 + API 双重守卫，admin 保护完整 |
| **KB 文档** | 70% | 18 份文档索引存在；`cross/02_order_status.md` 等未读取验证 |

### 11.3 当前提交节奏
- 近期聚焦：UI 增强（侧边栏分组、Holdings 视图）
- 底层 RPC / WS 通路已停滞 5+ commits
- **下一步明显待办**：连通 Push 队列消费 + 挂载 WS 路由

---

## 十二、待办 / 可疑点

### 12.1 🔴 高优先级（影响可用性）

1. **WebSocket 路由未挂载**（`server/main.py`）
   - `WSManager` 类已实现，但 `app.websocket("/ws/{channel}")` 缺失
   - 前端 `stores/ws.js` 重连逻辑已写好但**只在 Dashboard 占位调用**
   - 表现：5s 轮询代替实时推送，状态更新滞后

2. **Push 队列消费者未实现**（`server/rpc/`）
   - `EvTrade.Test.Push` 队列没有任何消费端
   - 后果：柜台回报无法落地，订单状态变化、成交回报全部丢失
   - 必须实现：消费者 → 解析 MsgPacket → 更新内存 dataclass → 触发 WS 广播

3. **XtQuant 本地直连 vs RPC 方案不一致**（`server/services/xtquant.py`）
   - `xtquant.py` 是本地 SDK 封装（**硬编码 Windows 路径** `D:\software\trade\iQuant\userdata`、`ACCOUNT_ID = '410001265100'`）
   - KB 描述的"msgpacket RPC 方案"才是生产推荐
   - 当前 `get_asset` 走本地、`qry_*` 走 RPC，**两套并行**，Linux 部署会因路径问题无法启动
   - **建议**：明确技术路线，删除其中一套或标注为开发/生产双模式

### 12.2 🟡 中优先级（代码质量）

4. **硬编码配置未抽离到 `config.py`**
   - `xtquant.py` 顶部 `TRADE_PATH` / `ACCOUNT_ID` / `SESSION_ID` 应支持 `EVTRADE_*` 环境变量

5. **`main.py:on_startup` 未自动 `init_trader()`**
   - 即使本地方案，XTP 连接也没在启动时建立
   - 表现：第一次请求 `get_asset` 才会触发连接，失败无重试

6. **`auth/__init__.py` 是空文件（0 字节）**
   - 当前无影响，但破坏 `from server.auth import ...` 命名空间一致性

7. **价格类型枚举字符串/数字不一致**
   - 项目代码：`'LIMIT' / 'LATEST' / 'FAIR'`（字符串）
   - 前端 `OrderForm.vue`：`11 / 5 / 14 / 44`（柜台数字）
   - `demo_rpc_client.py`：`"0"`（裸字符串数字）
   - **需统一约定**，在 `rpc/client.py` 加集中映射表

8. **Token 无主动失效机制**
   - `POST /api/auth/logout` 后端无操作，token 24h 内仍有效
   - 改密后旧 token 仍可用
   - **建议**：维护 token 黑名单（Redis 或 DB 表）

### 12.3 🟢 低优先级（清理/规范）

9. **`server/2.0` 文件是误提交**
   - 内容是 pip install 日志（2.7KB），不是 Python 文件
   - **建议删除** + 加 `.gitignore`

10. **`auth.py` 中 `logout` 端点无业务逻辑**
    - 仅返回 `{ "message": "ok" }`，JWT 仍在客户端生效

11. **5s 轮询 + 静态 URL**
    - `Trade.vue` / `Orders.vue` 轮询未实现页面隐藏时暂停（**会持续消耗 API**）
    - 建议：监听 `document.visibilitychange` 暂停

12. **错误处理吞掉异常**
    - `stores/auth.js:fetchMe` 失败时静默 `clear()`，无 toast 提示
    - 多个 try/except 块 `pass` 或 `return null`，无日志

13. **KB 文档索引与文件不一致**
    - `kb/README.md` 索引提到 `cross/02_order_status.md` 等文档可能不存在或待补
    - 建议 `ls kb/` 验证并清理索引

14. **`client/src/components/` 与 `views/` 命名风格**
    - `OrderForm.vue` 在 components，`Holdings.vue` 在 views
    - 建议统一：业务页面放 views，通用 UI 控件放 components

15. **ECharts 仅在 Dashboard 使用**
    - 包体大（~1MB），建议按需引入

### 12.4 ⚠️ 安全注意

16. **`.env` / `.env.sc` 中凭证暴露**
    - 虽然 `.gitignore` 排除（推测），但 `.env.sc` 存在表明可能曾被跟踪
    - 建议：定期审计 `git log --all -- .env*` + 立即轮换 RabbitMQ 密码 / secret key

17. **JWT 密钥持久化文件 `server/auth/.secret_key`**
    - 持久化意味着容器重建后旧 token 仍可解码
    - 建议生产用 `EVTRADE_SECRET` 环境变量而非文件

---

## 十三、如何运行项目

### 13.1 脚本化启动（推荐）

`scripts/dev.sh`（bash 版本）：
```bash
# 进入项目根
cd /root/workspcae/codespace/EvTrade

# 启动（默认后台）
./scripts/dev.sh start

# 查看状态
./scripts/dev.sh status

# 停止
./scripts/dev.sh stop

# 重启
./scripts/dev.sh restart

# 查看日志
./scripts/dev.sh logs [backend|frontend]
```

`scripts/dev.ps1`（Windows PowerShell 版本，同等接口）。

### 13.2 手动启动

#### 后端
```bash
cd /root/workspcae/codespace/EvTrade/server

# 1. 准备 Python 环境（建议 3.10+）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖（requirements.txt 需自行准备或从 KB/server/06_xtquant.md 推断）
pip install fastapi uvicorn[standard] sqlalchemy python-jose[cryptography] \
            passlib[bcrypt] python-multipart bcrypt aio-pika pydantic

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env：填入 RabbitMQ URL、secret key 等

# 4. 初始化数据库（自动建表 + seed admin）
python -c "from db import init_db; init_db()"

# 5. 启动
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

#### 前端
```bash
cd /root/workspcae/codespace/EvTrade/client

# 1. 安装依赖
npm install  # 或 pnpm install / yarn

# 2. 启动开发服务器
npm run dev
# 访问 http://localhost:3000
```

### 13.3 端口约定

| 服务 | 端口 | 备注 |
|---|---|---|
| 前端 (Vite dev) | 3000 | 代理 `/api` `/ws` → 8002 |
| 后端 (Uvicorn) | 8002 | **8000/8001 被占用** |
| RabbitMQ | 5672 | 默认 `amqp://guest:guest@192.168.10.2:5672/` |

### 13.4 默认账号
- 用户名：`admin`
- 密码：`admin123`
- 角色：`admin`
- 首次启动且 `users` 表为空时自动 seed

### 13.5 验证步骤
1. 浏览器打开 `http://localhost:3000`
2. 用 `admin` / `admin123` 登录
3. Dashboard 应显示资产概览（**注意：get_asset 走本地 XtQuant，未启动会失败**）
4. Trade 页可下单（下单走 RPC，**需 RabbitMQ + iQuant 联通**）
5. Users 页可管理用户（admin 限定）

### 13.6 故障排查
- **后端 502 / 拒绝连接**：检查端口 8002 是否被占用
- **前端白屏**：检查 Vite 代理 target 是否为 8002
- **下单超时**：检查 RabbitMQ 联通性（`amqp://192.168.10.2:5672/`）
- **资产查询失败**：检查 `xtquant.py` 路径（Windows 路径在 Linux 下会失败）
- **Push 队列无响应**：消费端尚未实现，是已知 TODO

---

## 附录 A：项目目录树

```
EvTrade/
├── README.md                 # 实际是 MsgPacket 协议 API 文档
├── scripts/
│   ├── dev.sh                # bash 启停脚本
│   ├── dev.ps1               # Windows PowerShell 版本（推测）
│   └── README.md             # 端口约定
├── kb/                       # 18 份知识库文档
│   ├── README.md             # 索引
│   ├── 00_overview.md
│   ├── 01_architecture.md
│   ├── cross/                # 横切关注点
│   │   ├── 01_data_models.md
│   │   ├── 02_order_status.md（推测）
│   │   ├── 03_role_matrix.md
│   │   └── 04_iquant.md
│   └── server/               # 后端专题
│       ├── 01_api.md
│       ├── 02_auth.md
│       ├── 03_db_models.md（推测）
│       ├── 04_services.md（推测）
│       ├── 05_rpc_client.md（推测）
│       ├── 06_xtquant.md
│       └── 07_websocket.md
├── server/                   # FastAPI 后端
│   ├── main.py               # 入口
│   ├── config.py             # 配置
│   ├── db.py                 # ORM 基础设施
│   ├── .env.example          # 配置模板
│   ├── .env                  # ⚠️ 含凭证
│   ├── .env.sc               # ⚠️ 含凭证
│   ├── 2.0                   # ⚠️ 误提交的 pip 日志
│   ├── test_rpc.py
│   ├── api/                  # REST 路由
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── orders.py
│   │   ├── trades.py
│   │   ├── positions.py
│   │   ├── asset.py
│   │   └── holdings.py
│   ├── auth/                 # 鉴权
│   │   ├── __init__.py       # 空
│   │   ├── security.py
│   │   └── deps.py
│   ├── models/               # 数据模型
│   │   ├── user.py
│   │   └── types.py
│   ├── services/             # 业务服务
│   │   ├── xtquant.py
│   │   └── trading.py
│   ├── rpc/                  # msgpacket RPC
│   │   └── client.py
│   └── ws/                   # WebSocket
│       └── manager.py
├── client/                   # Vue 3 前端
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── api/index.js
│       ├── router/index.js
│       ├── stores/           # Pinia
│       │   ├── auth.js
│       │   ├── order.js
│       │   ├── position.js
│       │   ├── asset.js
│       │   └── ws.js
│       ├── views/
│       │   ├── Login.vue
│       │   ├── Layout.vue
│       │   ├── Dashboard.vue
│       │   ├── Trade.vue
│       │   ├── Orders.vue
│       │   ├── Position.vue
│       │   ├── Holdings.vue
│       │   ├── Asset.vue
│       │   ├── Users.vue
│       │   └── Profile.vue
│       └── components/
│           ├── OrderForm.vue
│           ├── PositionTable.vue
│           └── PositionDetail.vue
└── iquant/                   # 参考实现（GBK 编码）
    ├── xtquant_api.py
    ├── demo_rpc_client.py
    └── demo_builder.py
```

---

## 附录 B：关键术语表

| 术语 | 解释 |
|---|---|
| **QMT / MiniQMT** | 迅投量化交易终端，券商部署的 Windows 本地程序 |
| **XtQuant** | 迅投 Python SDK，对接 miniQMT 的库 |
| **iQuant** | 与 MiniQMT 同体系的产品名 |
| **msgpacket** | 自研二进制通信协议（`magic='YSWY'`），用于柜台/客户端解耦 |
| **aio-pika** | Python 异步 RabbitMQ 客户端 |
| **XTP** | 中泰证券极速交易柜台（XtQuant 后端之一） |
| **JWT** | JSON Web Token，本项目用 HS256，24h 有效 |
| **RBAC** | Role-Based Access Control，本项目三角色 |
| **TO管理** | T+0 持仓管理（侧边栏改名后） |
| **holdings** | 期初持仓（按日初始化持仓的视图） |

---

**报告完成时间**：基于当前 git 工作区
**探查范围**：31 个源文件 + 10 份 KB 文档 + git log + 配置文件
**未读取**：`.env` / `.env.sc`（含敏感值）、`server/2.0`（已确认是误提交文件）、`server/auth/__init__.py`（空）、部分 `kb/cross/02_order_status.md` 等索引存在但未读取的 KB 文档
