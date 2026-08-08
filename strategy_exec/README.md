# strategy_exec — 独立策略运行服务

EvTrade 项目的策略运行独立服务（change `2026-08-09-strategy-exec-service`）。

- 基于 **Backtrader** 引擎（业界标准回测/实盘框架）
- 通过 **RabbitMQ** 推送 signal 给 EvTrade 交易端
- 通过 **HTTP REST** 接收 EvTrade 启动/停止指令
- 与 EvTrade 主进程共享 MySQL DB（`strategy_script` / `strategy_task` / `strategy_script_audit`）

## 启动

```bash
# 1. 装依赖（独立 venv）
cd strategy_exec
uv sync                # 或 pip install -e .

# 2. 复制环境变量
cp .env.example .env
# 编辑 .env：填 EVTRADE_DB_URL / EVTRADE_RABBITMQ_URL / STRATEGY_EXEC_API_TOKEN

# 3. 启动
python -m strategy_exec.main --port 8001
# 或
python scripts/evctl_strategy_exec.py start
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
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── Dockerfile
├── strategy_exec/
│   ├── __init__.py
│   ├── main.py                # FastAPI app 入口
│   ├── config.py              # Pydantic Settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── internal.py        # 4 endpoint (mock in Phase 1)
│   ├── templates/
│   │   └── default_bt_strategy.py  # Phase 5 默认 Backtrader demo
│   ├── engines/               # Phase 2 (Backtrader)
│   ├── data_access/           # Phase 2
│   ├── signal/                # Phase 2 (RabbitMQ publisher)
│   ├── market_data/           # Phase 2 (hqserver WS + history)
│   ├── sandbox/               # Phase 2 (用户脚本 loader)
│   ├── risk/                  # Phase 2 (占位, 无风控)
│   └── utils/
├── scripts/
│   └── evctl_strategy_exec.py  # start/stop/status/restart
└── tests/
```

## 阶段进度

| Phase | 状态 | 内容 |
|---|---|---|
| 1 | ✅ 本 commit | 骨架 + 配置 + 启动器 + mock API |
| 2 | ⏳ 待实施 | Backtrader 集成 + 数据访问 + 信号推送 |
| 3 | ⏳ 待实施 | EvTrade signal_consumer + 转发 |
| 4 | ⏳ 待实施 | 清理旧引擎 + DB 迁移 |
| 5 | ✅ 本 commit | 默认 demo 模板（其他文档/迁移留待后续）|

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

- SPEC: `openspec/changes/2026-08-09-strategy-exec-service/proposal.md`
- 设计: `openspec/changes/2026-08-09-strategy-exec-service/design.md`
- 任务: `openspec/changes/2026-08-09-strategy-exec-service/tasks.md`
- Spec delta: `openspec/changes/2026-08-09-strategy-exec-service/spec-deltas/strategy-exec.md`