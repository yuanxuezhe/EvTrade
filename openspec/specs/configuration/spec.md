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
| `STRATEGY_ENGINE_ENABLED` | `false` | 是否启用 strategy 引擎（REST 路由 + WS 推送；QuoteConsumer 不再受此控制） |
| `HQ_WS_URL` | `ws://127.0.0.1:8765` | hqserver WebSocket 地址（QuoteConsumer 接入点，与 hqserver.HQ_WS_PORT 对应） |

- **STRATEGY_ENGINE_ENABLED 语义**（2026-07-09 重构：QuoteConsumer 与策略引擎解耦）：
  - `false`（默认）：strategy REST 路由除 `/api/strategy/flags` 外全部返 503；**QuoteConsumer 仍然启动**（行情 7×24，与策略独立）；前端 `/strategy-trade` 路由可访问但所有数据为空
  - `true`：策略 REST 路由正常工作；QuoteConsumer 启动（与之前行为相同）
- **HQ_WS_URL**：
  - 与 `HQ_WS_HOST` / `HQ_WS_PORT` 组合（`ws://{HQ_WS_HOST}:{HQ_WS_PORT}`）语义一致；用 URL 形式便于部署时切换网络拓扑
  - QuoteConsumer 默认 `ws://127.0.0.1:8765`（与 hqserver 同机）；跨机部署时需显式覆盖

### REQ-CFG-012: strategy_exec 服务 env（v120 strategy-exec-service，2026-08-09）

**EvTrade 侧**（`server/config.py`，`/tasks/{id}/run` + `/tasks/{id}/stop` 转发用）：

| Key | 默认 | 说明 |
|---|---|---|
| `STRATEGY_EXEC_API_URL` | `http://127.0.0.1:8001` | strategy_exec 服务 base URL（EvTrade 转发 POST /internal/run-task / stop-task）|
| `STRATEGY_EXEC_API_TOKEN` | `""` | `X-Internal-Token` header 值；strategy_exec 侧该 token 为空 = 局域网不鉴权 |

**strategy_exec 侧**（`strategy_exec/strategy_exec/config.py`，独立 `strategy_exec/.env`）：

| Key | 默认 | 说明 |
|---|---|---|
| `STRATEGY_EXEC_PORT` / `STRATEGY_EXEC_HOST` | `8001` / `0.0.0.0` | 监听端口 / host |
| `STRATEGY_EXEC_API_TOKEN` | `""` | 校验 `X-Internal-Token`；空 = 不鉴权（局域网部署）|
| `EVTRADE_STRATEGY_EXCHANGE_NAME` | `strategy.exchange` | signal topic exchange（durable）|
| `EVTRADE_STRATEGY_SIGNAL_QUEUE` | `EvTrade.StrategySignal` | signal queue（durable，EvTrade signal_consumer 订阅）|
| `EVTRADE_STRATEGY_PUBLISH_CONFIRM_TIMEOUT` | `5` | publisher confirm 超时（秒）|
| `EVTRADE_STRATEGY_PUBLISH_RETRIES` | `3` | 推送失败重试次数 |
| `EVTRADE_HIS_HQ_EXCHANGE_NAME` / `EVTRADE_HIS_HQ_REQ_QUEUE` / `EVTRADE_HIS_HQ_REQ_TIMEOUT` | `quota_his.exchange` / `EvTrade.ReqHisHq` / `30` | 历史 K 线 RabbitMQ 拓扑 |
| `HQ_WS_URL` | `ws://127.0.0.1:8765/quota.broadcast` | hqserver 实时行情 WS（实盘 tick 订阅，自动重连）|
| `SANDBOX_BLOCKED_MODULES` / `SANDBOX_ALLOWED_MODULES` | 见 REQ-SE-006 | 用户脚本沙箱 import 黑/白名单 |
| `EVTRADE_DB_URL` / `EVTRADE_RABBITMQ_URL` | 必填 | 复用 EvTrade 同库 / 同 RabbitMQ |

- strategy_exec 复用 EvTrade 根 `.venv`（pydantic v2 + `pydantic-settings`），无独立 pyproject.toml/Dockerfile
- 启动：`python -m strategy_exec.main --port 8001` 或 `strategy_exec/scripts/evctl_strategy_exec.py`
- 详见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-001（部署）/ REQ-SE-002（internal endpoint 鉴权）/ REQ-SE-004（RabbitMQ 拓扑）

### REQ-CFG-009: MySQL 数据库连接（v14 sqlite → mysql 迁移，v20 强制 MySQL-only 永久标准）

| Key | 默认 | 说明 |
|---|---|---|
| `EVTRADE_DB_URL` | **无默认；必须显式设置** | SQLAlchemy URL（driver=pymysql 纯 Python，跨平台零编译）。**未设置或非 MySQL → 进程拒绝启动（RuntimeError）** |
| `EVTRADE_DB_ADMIN_URL` | 留空 | **DDL-only URL**（init_db 建表 / 一次性 migration 用）。生产部署完成后建议从 env 删除避免误用 |
| `EVTRADE_DB_POOL_SIZE` | `5` | MySQL pool size |
| `EVTRADE_DB_MAX_OVERFLOW` | `10` | 超额连接上限 |
| `EVTRADE_DB_POOL_RECYCLE` | `1800` | 连接回收秒数（防止 MySQL 8 wait_timeout 主动断开） |
| `EVTRADE_DB_POOL_PRE_PING` | `true` | 断连自动重连（防 wait_timeout 后 stale connection） |
| `EVTRADE_DB_POOL_TIMEOUT` | `10` | **v51 起** Pool 等连接超时（秒）。默认 10s（SQLAlchemy 默认 30s）。**v52 复盘**：30s 太长，触发 futex_wait_queue 后主进程僵死；10s 快速失败 → 5xx → 客户端重试，避免雪崩 |

- **driver 唯一**：pymysql（纯 Python）— 已写进 `requirements.txt` + 已装到 host Python 3.13
- **v20 强制 MySQL-only 永久标准**：
  - `EVTRADE_DB_URL` **未设置** → `infra/db.py` 启动时 `os.environ["EVTRADE_DB_URL"]` 抛 `KeyError` → 包装为 `RuntimeError`
  - `EVTRADE_DB_URL` **非 MySQL**（如 `sqlite:///...`）→ `infra/db.py` 启动时 `assert db.bind.dialect.name == "mysql"` 抛 `RuntimeError`，明确文案 `"[infra.db] Only MySQL is supported (v20 permanent standard). SQLite has been permanently disabled."`
  - migration 脚本同样强制：`os.environ["EVTRADE_DB_URL"]` + `assert startswith("mysql")`（`server/migrations/2026-07-{06,08,09}-*.py`）
  - 仓库存量 SQLite fallback 代码（`_DEFAULT_SQLITE_URL` / `is_mysql` 双 driver 分支 / SQLite PRAGMA hook / SQLite list-of-dict 占位符）**全部删除**
- **密码特殊符号 URL encode**：`@` → `%40`、`#` → `%23`
- **字符集**：服务端 `utf8mb4` / 排序规则 `utf8mb4_unicode_ci`（连接参数 `charset=utf8mb4`）
- **存储引擎**：InnoDB（MySQL 8.0 默认；事务 + FK + 行锁全支持）
- **池配置**：MySQL 走 `QueuePool + pool_size/max_overflow/recycle/pre_ping`
- **legacy 兼容常量**：`BASE_DIR` 保留在 `infra/db.py` 供 `migrations/` 用，`DB_PATH` **永久下线**（`server/db.py` facade 移除该 re-export）
- **历史工具**：`server/migrations/sqlite-to-mysql-migrate.py` 保留（一次性历史工具，不参与日常启动）

### REQ-CFG-011: futex 僵死 "根治 vs 预防" 双保险（v52 立）

futex 僵死累计复发 3 次（v46 + v50 + v51），v52 复盘后明确分工：

| 维度 | 根治 (commit 22f515f) | 预防 (commit 51fcb9c) |
|---|---|---|
| 落点 | sync endpoint → async + bcrypt 走 `run_in_threadpool` | `pool_timeout=10s` + `pool_pre_ping=true` |
| 目标 | 释放 Starlette threadpool → DB session 立即归还 | 极端情况下快速 5xx，不让主进程僵死 |
| 必要性 | ✅ 必做（结构性消除） | ✅ 必做（兜底保险） |

- **新 endpoint 规范**：任何 sync CPU bound (bcrypt/hash/pinyin/计算) 都必须 `async def` + 走 threadpool
- **代码评审检查点**：sync def + `bcrypt.*` / `hashlib.*` / `pypinyin.*` 调用 → 必须 reject
- **spec 落点**：`server/infra/db.py::_pool_kwargs` docstring 完整记录 7 步死锁链 + v52 修复路径
- **Known Issue**：40+ 并发 login 仍会触发 pool 满（容量 5+10=15），但不会触发 futex 僵死（health endpoint 仍响应）

### REQ-CFG-010: 双用户最小权限（v14 MySQL 安全姿态）

业务库 `evtrade` 两类用户，按用途严格隔离：

| User | 密码 | 权限范围 | 用途 |
|---|---|---|---|
| `EvTrade` | `p%40ssw0rd` | `SELECT/INSERT/UPDATE/DELETE` ON `evtrade.*` | runtime 业务账号 |
| `evtrade_dba` | `p%40ssw0rd` | `SELECT/INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/INDEX/REFERENCES` ON `evtrade.*` | init_db 建表 / 一次性 migration |
| `root` | `p%40ssw0rd` | `localhost` socket only（TCP 远程拒登 + `ACCOUNT LOCK`）| 容器内紧急维护 |

- **最小权限原则**：业务账号无 DDL，攻击面收敛到数据行；DDL 走专门 dba 账号
- **DDL admin 账号生命周期**：部署 → init_db → 可选 `REVOKE` / `DROP USER evtrade_dba`（详见 ops docs）
- **密码 URL encode**：业务账号在 DSN 里必须 `p%40ssw0rd`（`@` 已编码）

#### Scenario: STRATEGY_ENGINE_ENABLED=false 时访问 REST

- **GIVEN** STRATEGY_ENGINE_ENABLED=false
- **WHEN** GET /api/strategy
- **THEN** MUST 返 503（与 SPEC REQ-STRAT-009 同步）

#### Scenario: HQ_WS_URL 跨机部署

- **GIVEN** HQ_WS_URL=ws://10.0.0.5:8765
- **WHEN** QuoteConsumer start
- **THEN** MUST 连接 ws://10.0.0.5:8765（非默认 127.0.0.1）

#### Scenario: S-CFG-006 (新增): 业务账号 DDL 被拒

**Given** FastAPI runtime 用 `EVTRADE_DB_URL`（业务账号）  
**When** 业务代码意外调 `CREATE TABLE` 或 `ALTER TABLE`  
**Then** MUST 抛 `1142 CREATE command denied to user 'EvTrade'@'%'`  
**And** **不静默降级** —— 立刻暴露到日志，避免误用 DDL 走业务账号

#### Scenario: S-CFG-007 (新增): MySQL 8 wait_timeout 自动重连

**Given** backend 闲置超过 `wait_timeout`（默认 28800s）  
**When** 下一次 SQL 请求落到 stale 连接  
**Then** SQLAlchemy `pool_pre_ping` 触发 ping → 失败 → 自动重连 → 请求正常完成  
**And** **不抛 2013 Lost connection 错误**

#### Scenario: S-CFG-008 (新增): SQLite dev fallback

**Given** `.env` 未设 `EVTRADE_DB_URL`  
**When** FastAPI 启动  
**Then** `infra/db.py` 退回 `sqlite:///./evtrade.db`  
**And** PRAGMA foreign_keys 启用（让 dev 行为对齐 MySQL FK 语义）  
**And** `pool_*` 配置跳过（StaticPool）

#### Scenario: S-CFG-009 (新增): admin URL 缺失时 DDL 报错

**Given** `.env` 仅设 `EVTRADE_DB_URL`（业务账号）未设 `EVTRADE_DB_ADMIN_URL`  
**When** 运维跑 `init_db()` 建表  
**Then** MySQL 抛 `1142 CREATE command denied`  
**And** 提示运维读 `REQ-CFG-009` / `REQ-CFG-010` 启用 `evtrade_dba` 账号或设 ADMIN_URL

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
