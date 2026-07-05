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

### REQ-CFG-004: 启动校验（`server/config.py::ConfigValidator`）

- 缺 `EVTRADE_SECRET` **且** `server/auth/.secret_key` 文件不存在 → 警告（不阻塞），首次启动时 `security.py::_load_or_create_secret()` 用 `secrets.token_urlsafe(64)` 自动生成并持久化到 `.secret_key`
- 多实例部署（如生产双活）必须显式设置 `EVTRADE_SECRET` 环境变量以共享 token；单实例可依赖 auto-gen
- `EVTRADE_RABBITMQ_URL` 为空 → 启动失败（`RuntimeError` from `validate_config()`）
- `EVTRADE_RPC_TIMEOUT` ≤ 0 或 > 300 → 警告（建议 5-120s）
- `EVTRADE_API_PORT` 越界（<1 或 >65535）→ 启动失败

### REQ-CFG-005: 凭证脱敏

- ❌ **绝不** commit `server/.env`
- ✅ `.env.example` 允许 commit，但所有敏感字段值替换为 `<SET_IN_ENV>`
- ✅ 历史扫描无 `.env` 泄漏（已验证 `git log --all -- server/.env` 为空）

### REQ-CFG-006: 必填项校验测试覆盖

- `server/test_config.py` 单测覆盖 `ConfigValidator` 的 4 个分支
- Settings 是 `frozen=True` dataclass，测试用 `object.__setattr__` 绕过冻结

### REQ-CFG-007: 系统状态机（v5 schema refactor）

- 表名：`trading_day` → **`sys_status`**
- 主键：`trd_date`（YYYYMMDD），去 `id` 自增
- 状态字段：`status` ∈ {`pending`, `active`, `closed`}
- 其他字段：`is_half_day` / `initialized_at` / `initialized_by` / `closed_at` / `closed_by` / `remark` / `created_at`
- URL：`/api/admin/trading-day*` → **`/api/admin/sys-status*`**
- Pydantic：`TradingDayOut` → **`SysStatusOut`**，字段 `current_date` → **`trd_date`**

### REQ-CFG-008: Strategy engine env（strategy_trade）

| Key | 默认 | 说明 |
|---|---|---|
| `STRATEGY_ENGINE_ENABLED` | `false` | 是否启用 strategy 引擎（REST 路由 + WS 推送 + QuoteConsumer 启动统一开关） |
| `HQ_WS_URL` | `ws://127.0.0.1:8765` | hqserver WebSocket 地址（QuoteConsumer 接入点，与 hqserver.HQ_WS_PORT 对应） |

- **STRATEGY_ENGINE_ENABLED 语义**：
  - `false`（默认）：strategy REST 路由除 `/api/strategy/flags` 外全部返 503；QuoteConsumer 不启动；前端 `/strategy-trade` 路由可访问但所有数据为空
  - `true`：全功能启用；QuoteConsumer 在 app startup 启动；REST 路由正常工作
- **HQ_WS_URL**：
  - 与 `HQ_WS_HOST` / `HQ_WS_PORT` 组合（`ws://{HQ_WS_HOST}:{HQ_WS_PORT}`）语义一致；用 URL 形式便于部署时切换网络拓扑
  - QuoteConsumer 默认 `ws://127.0.0.1:8765`（与 hqserver 同机）；跨机部署时需显式覆盖

#### Scenario: STRATEGY_ENGINE_ENABLED=false 时访问 REST

- **GIVEN** STRATEGY_ENGINE_ENABLED=false
- **WHEN** GET /api/strategy
- **THEN** MUST 返 503（与 SPEC REQ-STRAT-009 同步）

#### Scenario: HQ_WS_URL 跨机部署

- **GIVEN** HQ_WS_URL=ws://10.0.0.5:8765
- **WHEN** QuoteConsumer start
- **THEN** MUST 连接 ws://10.0.0.5:8765（非默认 127.0.0.1）

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

### S-CFG-004: JWT_SECRET auto-gen（新增）

Given `.env` 无 `EVTRADE_SECRET=` 行 且 `server/auth/.secret_key` 不存在
When FastAPI 首次启动
Then `security.py::_load_or_create_secret()` 用 `secrets.token_urlsafe(64)` 生成 64 字节随机密钥
And 写入 `server/auth/.secret_key`（持久化，重启后 token 不失效）
And `ConfigValidator` 输出 `[WARN] EVTRADE_SECRET 未设置，首次启动将自动生成` 但不阻塞启动
And 后续 token 签名/校验正常工作

### S-CFG-005: API_PORT 越界（新增）

Given `.env` 设 `EVTRADE_API_PORT=99999`
When FastAPI 启动
Then `ConfigValidator.validate()` 检测到端口越界 → 加入 `errors` 列表
And `validate_config()` 抛 `RuntimeError: Config validation failed: ['INVALID_API_PORT: 99999']`
And uvicorn 退出码非 0

## Known Issues (from analysis)

- ✅ **`JWT_SECRET` 启动校验**：REQ-CFG-004 已重写 + REQ-CFG-006 测试覆盖
- 🟡 配置分散在 `server/config.py` 和 `hq/hqserver.py` 两处，**没共用** Settings 类（保留为下个 change）
- 🟢 `.env.example` 已包含所有 EVTRADE_* 和 HQ_* key，本轮新增的 HQ_* 已合并
