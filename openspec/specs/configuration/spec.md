# configuration — 配置与环境变量

## Purpose

EvTrade 部署在 Windows（开发/QMT 柜台）+ Linux（前后端服务），配置必须：
- **不泄露**敏感信息到 git
- **可覆盖**（.env 优先级最高）
- **启动时校验**（缺关键配置立刻退出，不要运行时才炸）
- **分层**（FastAPI 配置 + hqserver 配置，共用同一个 .env）

## Requirements

### REQ-CFG-001: 配置文件位置

- `server/.env` — 主配置，git ignored
- `server/.env.example` — 模板，**已 commit**，含所有 key（值脱敏）
- `server/.env.sc` — 备用配置（开发分支切换），git ignored

### REQ-CFG-002: FastAPI 配置（server/config.py）

| Key | 默认 | 说明 |
|---|---|---|
| `EVTRADE_RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ 连接串 |
| `EVTRADE_EXCHANGE_NAME` | `EvTrade.Test.Req` | RPC 请求 exchange |
| `EVTRADE_QUEUE_REQ` | `EvTrade.Test.Req` | RPC 请求队列 |
| `EVTRADE_QUEUE_REPLY` | `EvTrade.Test.Reply` | RPC 应答队列 |
| `EVTRADE_QUEUE_PUSH` | `EvTrade.Test.Push` | 柜台推送队列 |
| `EVTRADE_RPC_TIMEOUT` | `30.0` | RPC 调用超时（秒） |
| `EVTRADE_API_HOST` | `0.0.0.0` | FastAPI 监听地址 |
| `EVTRADE_API_PORT` | `8000` | FastAPI 监听端口 |
| `JWT_SECRET` | ⚠️ **必填** | JWT 签名密钥 |
| `JWT_EXPIRE_MINUTES` | `60` | Token 过期 |
| `JWT_ALGORITHM` | `HS256` | JWT 算法 |

### REQ-CFG-003: hqserver 配置（hq/hqserver.py）

| Key | 默认 | 说明 |
|---|---|---|
| `HQ_RABBITMQ_URL` | `amqp://192.168.10.2:5672/` | 行情源 RabbitMQ |
| `HQ_EXCHANGE_NAME` | `quota.exchange` | 上游 FANOUT exchange |
| `HQ_SOURCE_QUEUE` | `EvQuota` | 上游行情队列 |
| `HQ_BROADCAST_EXCHANGE` | `quota.broadcast.exchange` | 下游 Topic exchange（兼容旧版） |
| `HQ_NUM_WORKERS` | `4` | 协程池大小 |
| `HQ_MAX_QUEUE_SIZE` | `5000` | 内部缓冲区 |
| `HQ_PREFETCH_COUNT` | `16` | aio-pika 预取数 |
| `HQ_WS_HOST` | `0.0.0.0` | WS 监听地址 |
| `HQ_WS_PORT` | `8765` | WS 监听端口 |

### REQ-CFG-004: 启动校验

- 缺 `JWT_SECRET` → 启动失败 + 明确错误信息
- `EVTRADE_RABBITMQ_URL` 解析失败 → 启动失败
- 端口被占用 → 启动失败（uvicorn 已有错误信息）

### REQ-CFG-005: 凭证脱敏

- ❌ **绝不** commit `server/.env`
- ✅ `.env.example` 允许 commit，但所有敏感字段值替换为 `<SET_IN_ENV>`
- ✅ 历史扫描无 `.env` 泄漏（已验证 `git log --all -- server/.env` 为空）

### REQ-CFG-006: 系统状态机（v5 schema refactor）

- 表名：`trading_day` → **`sys_status`**
- 主键：`trd_date`（YYYYMMDD），去 `id` 自增
- 状态字段：`status` ∈ {`pending`, `active`, `closed`}
- 其他字段：`is_half_day` / `initialized_at` / `initialized_by` / `closed_at` / `closed_by` / `remark` / `created_at`
- URL：`/api/admin/trading-day*` → **`/api/admin/sys-status*`**
- Pydantic：`TradingDayOut` → **`SysStatusOut`**，字段 `current_date` → **`trd_date`**

## Scenarios

### S-CFG-001: 首次部署

Given 新克隆仓库  
When 开发者运行 `./scripts/dev.sh start`  
Then 启动失败提示"请复制 server/.env.example 到 server/.env 并设置 JWT_SECRET"

### S-CFG-002: 切换环境

Given 开发者有 dev/prod 两套 .env  
When 切换时用 `cp server/.env.dev server/.env`  
Then 重启服务即可生效

### S-CFG-003: RabbitMQ 不可达

Given `.env` 中 URL 拼错  
When FastAPI 启动  
Then RPC 客户端尝试连接 → 超时 → log 错误但**不崩溃**（设计：行情/委托/查询全部降级为失败响应，前端显示错误）

## Known Issues (from analysis)

- 🟡 `JWT_SECRET` 当前**没有**启动校验（缺失时用 `dev-secret-please-change` 静默通过）
- 🟡 配置分散在 `server/config.py` 和 `hq/hqserver.py` 两处，**没共用** Settings 类
- 🟢 `.env.example` 已包含所有 EVTRADE_* 和 HQ_* key，本轮新增的 HQ_* 已合并
