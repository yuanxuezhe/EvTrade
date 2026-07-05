## ADDED Requirements

### Requirement: 策略引擎启动开关 + hqserver WS URL（REQ-CFG-008）

`server/.env` MUST 新增 2 个环境变量：

| 变量 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `STRATEGY_ENGINE_ENABLED` | bool | `false` | 策略引擎总开关；false 时 quote_consumer 不启动 + API 返 503 |
| `HQ_WS_URL` | str | `ws://localhost:8765/ws/quote` | 后端连接 hqserver 的 WebSocket URL（与前端独立） |

#### Scenario: 默认配置（v1 灰度安全）

- **WHEN** `.env` 未设置 `STRATEGY_ENGINE_ENABLED`
- **THEN** 后端启动时 MUST NOT 启动 QuoteConsumer（默认 false）
- **AND** `/api/strategy/*` 端点 MUST 返 503 `{code: 'ENGINE_DISABLED', msg: 'strategy engine is disabled'}`

#### Scenario: 启用 + 自定义 WS URL

- **WHEN** `.env` 设 `STRATEGY_ENGINE_ENABLED=true` + `HQ_WS_URL=ws://10.0.0.5:8765/ws/quote`
- **THEN** QuoteConsumer MUST 连接到自定义 URL
- **AND** API 端点正常服务

#### Scenario: 启动时校验

- **WHEN** `STRATEGY_ENGINE_ENABLED=true` 但 `HQ_WS_URL` 格式非法（非 ws:// 开头）
- **THEN** 后端启动 MUST 抛 ConfigurationError 并退出（沿用现有 `config.py` 启动校验模式）

#### Scenario: 配置分层

- **WHEN** `server/.env` 与 `server/.env.local` 同时设置 `STRATEGY_ENGINE_ENABLED`
- **THEN** `.env.local` 优先级更高（沿用现有 pydantic BaseSettings 优先级）