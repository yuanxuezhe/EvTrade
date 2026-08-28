# strategy_exec — 独立策略运行服务

EvTrade 项目的策略运行独立服务（change `2026-08-09-strategy-exec-service`）。

- 基于 **Backtrader** 引擎（业界标准回测/实盘框架）
- 通过 **RabbitMQ** 推送 signal 给 EvTrade 交易端
- 通过 **HTTP REST** 接收 EvTrade 启动/停止指令
- 与 EvTrade 主进程共享 MySQL DB（`strategy_script` / `strategy_task` / `strategy_script_audit`）

## 启动

> **依赖**：复用 EvTrade 根 `.venv`（pydantic v2 + `pydantic-settings`），无独立 pyproject.toml/Dockerfile（2026-08-09 决策，commit `154a36b`）。确保在 EvTrade 根环境已装 `backtrader` / `aio-pika` / `websockets` 等依赖。

```bash
# 1. 复制环境变量
cp .env.example .env
# 编辑 .env：填 EVTRADE_DB_URL / EVTRADE_RABBITMQ_URL / STRATEGY_EXEC_API_TOKEN

# 2. 启动（用根 .venv 的 python）
python -m strategy_exec.main --port 8001
# 或
uv run python ./scripts/evctl.py start strategy_exec
```

## 健康检查

```bash
curl http://localhost:8001/health
# {"status": "ok", "version": "0.1.0", "ts": "..."}
```

## REST API（internal）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET`  | `/health` | 健康检查 |
| `POST` | `/internal/run-task` | 启动任务（EvTrade 转发调用）|
| `POST` | `/internal/stop-task` | 停止任务 |
| `GET`  | `/internal/tasks/{task_id}/status` | 查任务状态 |
| `POST` | `/internal/tasks/{task_id}/progress` | 接收 progress 回调 |

所有 `/internal/*` endpoint 需校验 `X-Internal-Token` header。

详见 `openspec/changes/2026-08-09-strategy-exec-service/design.md` §4。

## 目录结构

```
strategy_exec/
├── README.md
├── .env.example
├── .gitignore
├── strategy_exec/
│   ├── __init__.py
│   ├── main.py                # FastAPI app 入口
│   ├── config.py              # Pydantic Settings（复用根 .venv, pydantic v2 + pydantic-settings）
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── internal.py        # 4 internal endpoint（run/stop/status/progress）
│   ├── templates/
│   │   └── default_bt_strategy.py  # 默认 Backtrader 双均线模板
│   ├── engines/
│   │   └── backtrader/        # adapter(ProjectStrategy) + backtest + live(LiveRunner)
│   ├── data_access/           # db + strategy_script + strategy_task（乐观锁）
│   ├── signal/                # RabbitMQ publisher（publisher confirms + 重试）
│   ├── market_data/           # hq_history(RabbitMQ) + hq_ws_client(hqserver WS)
│   └── sandbox/               # 用户脚本 loader（沙箱）
└── logs/                       # 运行时生成 (strategy_exec.pid, strategy_exec.log)
```

## 阶段进度

| Phase | 状态 | 内容 |
|---|---|---|
| 1 | ✅ | 骨架 + 配置 + 启动器 + 4 internal endpoint |
| 2 | ✅ | Backtrader 集成 + 数据访问 + 信号推送 |
| 3 | ✅ | EvTrade signal_consumer + 转发 endpoint |
| 4 | ✅ | 清理旧引擎 + DB 迁移（strategy_task +3 字段）|
| 5 | ✅ | 默认 demo 模板 + spec + 迁移指南 |

> 旧网格策略引擎（regime/grid）清理见 commit `aa70dae`；script-strategy 引擎迁移详见 `openspec/specs/strategy-exec/spec.md`。

## 依赖

- `fastapi` + `uvicorn` — HTTP 框架
- `sqlalchemy` + `pymysql` — DB（与 EvTrade 同库）
- `aio-pika` + `pika` — RabbitMQ（推送 signal / 收 broker his_hq）
- `backtrader` + `pandas` — 回测/实盘引擎（Phase 2）
- `pydantic` — 配置 + schema 校验
- `websockets` — 行情 WS（Phase 2）

## 调试

```bash
# 查看日志
tail -f /var/log/strategy_exec.log

# 查 RabbitMQ 队列
# strategy.exchange + EvTrade.StrategySignal queue

# 查 MySQL
mysql -h <host> -P 33066 -u EvTrade -p evtrade \
    -e "SELECT id, user_id, script_id, status, execution_service FROM strategy_task ORDER BY id DESC LIMIT 10;"
```

## 相关文档

- 能力 spec：`openspec/specs/strategy-exec/spec.md`（REQ-SE-001~007，已归档）
- 迁移指南：`docs/strategy-migration-v90-to-bt.md`（v90 用户脚本 → Backtrader）
- 任务: `openspec/changes/2026-08-09-strategy-exec-service/tasks.md`（归档前）