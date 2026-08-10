# spec-delta: configuration（新增 4 个环境变量）

## Purpose

strategy-exec-service change 加 4 个新环境变量，分别给 strategy_exec 独立 .env 和 EvTrade .env 用。

## ADDED Requirements

### REQ-CFG-012: strategy_exec 服务配置

`strategy_exec/.env` 新增：

| Env | 必填 | 默认 | 说明 |
|---|---|---|---|
| `STRATEGY_EXEC_PORT` | NO | 8001 | strategy_exec 服务端口 |
| `STRATEGY_EXEC_API_TOKEN` | YES | - | EvTrade 调 strategy_exec 的 internal token（32+ 字符）|
| `EVTRADE_DB_URL` | YES | - | MySQL 连接串（与 EvTrade 共享同一库）|
| `EVTRADE_RABBITMQ_URL` | YES | - | RabbitMQ 连接串（与 EvTrade 共享 broker）|
| `EVTRADE_STRATEGY_EXCHANGE_NAME` | YES | `strategy.exchange` | signal 推送 exchange 名 |
| `EVTRADE_STRATEGY_SIGNAL_QUEUE` | YES | `EvTrade.StrategySignal` | signal 推送 queue 名 |
| `HQ_WS_URL` | YES | `ws://127.0.0.1:8765/quota.broadcast` | 行情 WS（直连 hqserver）|
| `HIS_HQ_EXCHANGE_NAME` | YES | `quota_his.exchange` | 历史 K 线 exchange（与 EvTrade broker 共享）|
| `LOG_LEVEL` | NO | INFO | 日志级别 |

#### Scenario: strategy_exec 启动

- **WHEN** `python -m strategy_exec.main`
- **THEN** 加载 `.env` 全部 9 个变量
- **AND** 启动失败若 `STRATEGY_EXEC_API_TOKEN` 未配置 → 退出码 1 + 日志 "missing required env"

### REQ-CFG-013: EvTrade 端 strategy_exec 配置

`server/.env` 新增：

| Env | 必填 | 默认 | 说明 |
|---|---|---|---|
| `STRATEGY_EXEC_API_URL` | YES | `http://127.0.0.1:8001` | strategy_exec 服务 URL |
| `STRATEGY_EXEC_API_TOKEN` | YES | - | 与 strategy_exec 共享的 token |
| `EVTRADE_STRATEGY_EXCHANGE_NAME` | YES | `strategy.exchange` | signal 推送 exchange（与 strategy_exec 一致）|
| `EVTRADE_STRATEGY_SIGNAL_QUEUE` | YES | `EvTrade.StrategySignal` | signal 推送 queue（与 strategy_exec 一致）|

#### Scenario: EvTrade 启动校验

- **WHEN** `python -m uvicorn server.main:app`
- **THEN** 启动时校验 4 新 env
- **AND** 缺 `STRATEGY_EXEC_API_URL` 或 `STRATEGY_EXEC_API_TOKEN` → 启动失败 + 日志 "strategy-exec-service not configured"

### REQ-CFG-014: 共享 secret 管理

`STRATEGY_EXEC_API_TOKEN` 是 EvTrade 与 strategy_exec 共享的 secret：

- 推荐用 `openssl rand -hex 32` 生成
- 生产部署：用 vault / k8s secret 管理（不在 git 中提交）
- 开发环境：可写在 `.env`（已 git ignore）

#### Scenario: 共享 token 校验

- **WHEN** EvTrade POST `strategy_exec:8001/internal/run-task` 带 `X-Internal-Token: <token>`
- **THEN** strategy_exec 比对 `STRATEGY_EXEC_API_TOKEN`
- **AND** 一致返 202，不一致返 401 "invalid token"

## Cross References

- 完整 env 模板：`strategy_exec/.env.example`
- 部署：`dev-process-control/spec.md` §"进程管控"