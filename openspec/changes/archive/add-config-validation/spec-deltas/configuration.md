# Spec Delta — add-config-validation → configuration

## ADDED Requirements

### REQ-CFG-006: 必填项校验

> 在启动阶段必须校验以下项；缺失或非法立即失败（`RuntimeError` 或 Pydantic ValidationError）。

- `JWT_SECRET` 必须存在且非空（不允许默认值 `dev-secret-please-change`）
- `EVTRADE_RABBITMQ_URL` 必须可被 `pydantic.HttpUrl` 解析
- `EVTRADE_API_PORT` 必须是 `1-65535` 整数
- `EVTRADE_RPC_TIMEOUT` 必须是正数

#### Scenario S-CFG-004: JWT_SECRET 缺失

Given `.env` 中无 `JWT_SECRET=` 行  
When FastAPI 启动  
Then 在 import 阶段抛 `RuntimeError: JWT_SECRET must be set in server/.env`  
And uvicorn 退出码非 0

#### Scenario S-CFG-005: RabbitMQ URL 非法

Given `EVTRADE_RABBITMQ_URL=not-a-url`  
When 启动  
Then Pydantic 校验失败并显示具体字段

## MODIFIED Requirements

### REQ-CFG-002（修改）

| Key | 必填 | 默认 |
|---|---|---|
| `JWT_SECRET` | ✅ | — (无默认) |
| `EVTRADE_RABBITMQ_URL` | | `amqp://guest:guest@localhost:5672/` |
| ... | | ... |

## REMOVED Requirements

无
