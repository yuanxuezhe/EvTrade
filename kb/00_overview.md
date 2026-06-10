# 00 · 项目概览（Overview）

## 1. 项目目标

EvTrade 是一个面向 A 股场景的**智能交易终端**，定位介于"网页版 QMT"和"管理面板"之间：

- **.vue + Element Plus** 单页应用，仿桌面级暗色 / 亮色主题。
- **FastAPI** 担任业务网关，统一做鉴权、ORM、聚合 RPC 调用。
- **RabbitMQ + MsgPacket 协议**与下游交易柜台（xtquant / 模拟器）通信。
- **JPA 风格**领域模型（`Position` / `Order` / `Trade` / `Asset`）做内存计算。

## 2. 技术栈一览

### 2.1 前端（`client/`）

| 层 | 选型 | 关键文件 |
|----|------|----------|
| 框架 | Vue 3 Composition API | `src/main.js` |
| 路由 | vue-router 4 | `src/router/index.js` |
| 状态 | Pinia 2 | `src/stores/*.js` |
| UI | Element Plus 2 + zh-CN | `src/main.js` |
| 图表 | ECharts 5（按需引入 Line/Bar/Pie） | `src/components/EChart.vue` |
| HTTP | Axios 1（拦截器统一处理 401） | `src/api/index.js` |
| 构建 | Vite 5 | `vite.config.js` |
| 工具 | dayjs（时间格式化） | `src/utils/format.js` |

### 2.2 后端（`server/`）

| 层 | 选型 | 关键文件 |
|----|------|----------|
| Web 框架 | FastAPI | `server/main.py` |
| ORM | SQLAlchemy 1.4（声明式） | `server/db.py`、`server/models/*.py` |
| 数据库 | SQLite（`evtrade.db`） | `server/db.py` |
| 鉴权 | python-jose（HS256 JWT）+ bcrypt | `server/auth/security.py` |
| 依赖注入 | FastAPI Depends | `server/auth/deps.py` |
| 异步 RPC | aio-pika + MsgPacket | `server/rpc/client.py` |
| 交易适配 | xtquant（迅投 QMT） | `server/services/xtquant.py` |
| WebSocket | FastAPI WebSocket | `server/ws/manager.py` |

### 2.3 协议层（`iquant/`，`msgpacket`）

- `MsgPacket`：跨语言消息打包协议（`magic[4] + crc32[4] + body_len[4] + header(72) + body`）。
- 消息类型：`REQUEST('R') / ANSWER('A') / PUSH('P') / HEARTBEAT('H')`。
- 通信拓扑：客户端 → 交换机 `msgpacket.exchange`（topic）→ `EvTrade.Test.Req` 队列；应答通过 `EvTrade.Test.Reply` 队列按 `msg_id` 匹配 future；推送走 `EvTrade.Test.Push` 队列。

## 3. 目录结构

```
D:/workspace/EvTrade/
├── README.md                 # MsgPacket 协议说明
├── client/                   # 前端
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── api/index.js      # 业务/鉴权/用户 API
│       ├── router/index.js   # 路由表 + 守卫
│       ├── stores/           # auth, asset, order, position, ui
│       ├── utils/format.js   # 格式化 + 状态映射
│       ├── components/       # 11 个通用组件
│       └── views/            # 9 个页面
├── server/                   # 后端
│   ├── main.py               # FastAPI 入口
│   ├── db.py                 # SQLite + Session
│   ├── 2.0                   # 旧版入口（已不推荐）
│   ├── api/                  # 路由：auth, asset, orders, positions, trades, users
│   ├── auth/                 # security.py (JWT/bcrypt), deps.py (依赖)
│   ├── models/               # types.py (dataclass), user.py (ORM)
│   ├── services/             # trading.py (内存仓库), xtquant.py (QMT 适配)
│   ├── rpc/client.py         # 异步 RPC 客户端
│   ├── ws/manager.py         # WS 管理
│   └── evtrade.db            # SQLite 文件
├── iquant/                   # 协议/适配参考
│   ├── xtquant_api.py        # xtquant 完整示例
│   ├── demo_rpc_client.py    # RabbitMQ 客户端示例
│   └── demo_builder.py       # MsgPacket 多结果集示例
└── docs/superpowers/         # 项目级 superpowers 文档
```

## 4. 启动与运行

### 4.1 后端
```bash
cd server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
- 启动时自动 `init_db()` 建表；
- 若 `users` 表为空，自动 seed `admin / admin123`；
- JWT secret 自动持久化到 `server/auth/.secret_key`，可被 `EVTRADE_SECRET` 环境变量覆盖。

### 4.2 前端
```bash
cd client
npm install
npm run dev   # 启动 Vite，端口 3000
```
- Vite 代理：`/api → http://localhost:8000`、`/ws → ws://localhost:8000`。
- 主题 / 侧边栏状态持久化到 `localStorage`（`evtrade-theme` / `evtrade-sidebar`）。

## 5. 核心业务流

### 5.1 登录
```
Login.vue → authApi.login()
  → POST /api/auth/login (x-www-form-urlencoded)
  → OAuth2PasswordRequestForm 校验 → bcrypt → 创建 JWT(24h)
  → 返回 { access_token, expires_in, user }
  → tokenStorage.set → Pinia authStore.user
  → 跳转到 redirect 或 /
```

### 5.2 下单
```
Trade.vue → OrderForm.vue → orderStore.placeOrder()
  → POST /api/orders/place  { stock_code, direction, volume, price, price_type }
  → 鉴权 require_trader
  → orders.py 调 rpc.client.ord_stk()
  → 构造 MsgPacket(func=ord_stk, headers=stock_code,volume,price_type,price,direction)
  → publish 到 RabbitMQ exchange (routing_key=EvTrade.Test.Req)
  → 因为 XtQuant ord_stk 是 fire-and-forget，立即返回临时 order_id
  → 真实回报由柜台异步 push 到 EvTrade.Test.Push
```

### 5.3 持仓 / 委托 / 成交 / 资金 查询
所有查询接口都通过 `server/rpc/client.py` 的 `qry_*` 函数向 RabbitMQ 发包，监听 `EvTrade.Test.Reply` 队列的应答并解析。

### 5.4 实时推送（待接入）
`server/ws/manager.py` 实现了 `WSManager`，定义了 4 个通道：
- `order_update` / `trade_update` / `position_update` / `asset_update`
- 当前 `main.py` 未挂载 WebSocket 路由，仅为后续 EvTrade.Test.Push 消费端预留。

## 6. 默认账号与种子

| 字段 | 值 |
|------|----|
| 用户名 | `admin` |
| 密码 | `admin123` |
| 角色 | `admin` |
| 中文名 | 系统管理员 |
| 启用 | true |

Seed 逻辑：`server/main.py` 的 `on_startup` 钩子；幂等（只当 `count==0` 时插入）。

## 7. 角色权限三层模型

```
viewer   → 仅 GET 自身 / 公开数据
trader   → viewer 权限 + 下单/撤单/初始化持仓
admin    → trader 权限 + 用户管理 + 重置密码 + 启停账号
```

详见 `cross/03_role_matrix.md`。
