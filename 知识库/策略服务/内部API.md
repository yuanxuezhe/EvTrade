# 内部 API

## 对应代码路径

- `e:/EvTrade/strategy_exec/strategy_exec/api/internal.py`（internal 路由，481 行）
- `e:/EvTrade/strategy_exec/strategy_exec/api/health.py`（健康检查）

## 功能概述

strategy_exec 对 EvTrade 主服务暴露的 HTTP 接口：`GET /health`（无鉴权）+ `/internal` 前缀下 5 个任务端点（run-task / stop-task / status / progress / run-sweep-task）。除 `/health` 外全部经 `verify_internal_token` 校验 `X-Internal-Token` 请求头。调用方唯一：EvTrade 后端 endpoints.py 转发。

## 文件清单

| 代码文件 | 作用 |
|----------|------|
| `api/internal.py` | 5 个 internal 端点 + 鉴权依赖 + 全部 Pydantic schema + 后台任务调度 |
| `api/health.py` | `GET /health` 返 `{status, version, ts}`，探活用 |

## 核心实现

### 鉴权：verify_internal_token

```python
async def verify_internal_token(x_internal_token: Optional[str] = Header(None)) -> None
```

- `settings.strategy_exec_api_token` 为空 → **直接放行**（局域网部署不鉴权）。
- 缺 header → 401 `{"code": "MISSING_TOKEN"}`；值不符 → 401 `{"code": "INVALID_TOKEN"}`。

### GET /health（无鉴权）

响应 `HealthResponse`：`{"status": "ok", "version": "0.1.0", "ts": "<UTC isoformat>"}`。

### POST /internal/run-task（202）

请求 `RunTaskRequest`：

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `task_id` | int ≥1 | 任务 ID（EvTrade 已预建 strategy_task 行） |
| `user_id` | int ≥0 | 用户 ID |
| `strategy_id` | int ≥1 | 任务归属策略（v123 best_params 回写目标） |
| `script_id` | str 1~64 | strategy_script.id |
| `stock_code` | str 1~16 | 标的代码 |
| `mode` | `^(backtest\|live)$` | 运行模式 |
| `params` | Any，默认 `{}` | 策略参数（传 JSON 字符串会被 model_validator 自动 json.loads） |
| `backtest_start_date` | `^\d{8}$` 可选 | 回测起始日（回测模式必填） |
| `backtest_end_date` | `^\d{8}$` 可选 | 回测结束日（回测模式必填） |
| `period` | `^(1d\|1m\|5m\|15m\|30m\|60m)$` 可选 | K 线周期 |
| `fields` | str 可选 | his_hq 请求字段 |
| `parent_task_id` | int ≥1 可选 | v126 母单归因（signal_consumer 写 orders.task_id） |
| `strategy_name` | str ≤255 可选 | v126 子单 user_def |

处理流程：

- **backtest**：校验起止日期（缺 → 400 `MISSING_DATES`）→ `fetch_his_bars` 拉历史 K 线（失败 → 502 `BROKER_ERROR`，提示需启动 QMT his_hq 服务并消费 `EvTrade.ReqHisHq`；空数据 → 400 `NO_DATA`）→ `get_publisher().connect()` 预连接（绑定主 loop，防回测线程内 asyncio.run 临时 loop 报 "Event loop is closed"）→ `asyncio.create_task(_run_backtest_background(...), name=f"backtest-{task_id}")` 后台异步执行。
- **live**：`update_task_status(task_id, "running")` → `start_live_runner(...)`（失败 → 500 `LIVE_START_FAILED`）。

响应 `RunTaskResponse`：`{"task_id": n, "status": "accepted", "msg": "task n (mode) started in background"}`。

后台函数 `_run_backtest_background` 用 `asyncio.to_thread(run_backtest, ...)` 跑同步回测；异常时 `update_task_status(task_id, "failed", error_msg=...)`；v123 起传 `update_strategy_best=True`（单次回测成功后 params 回写 `strategy.best_params`）。

### POST /internal/stop-task

请求 `StopTaskRequest`：`{"task_id": int}`。

- live 任务在跑（`is_running(task_id)`）→ `stop_live_runner(task_id)` 立即停。
- 否则（回测）仅 `update_task_status(task_id, "stopped")` 标记。

响应 `StopTaskResponse`：`{"ok": bool, "task_id": n}`。

### GET /internal/tasks/{task_id}/status

读共享 DB `get_task(task_id)`；不存在 → 404 `TASK_NOT_FOUND`。响应 `TaskStatusResponse`：

| 字段 | 说明 |
|---|---|
| `task_id` / `status` / `mode` | 状态：pending/running/finished/failed/stopped |
| `started_at` / `finished_at` | isoformat 字符串或 null |
| `pnl` / `trades_count` | 数值（默认 0） |
| `progress` | dict（DB JSON 字段，非 dict 则 null） |
| `live_signals_count` | live_signals 列表长度 |

### POST /internal/tasks/{task_id}/progress

请求 `ProgressRequest`：`{"task_id": int, "progress": dict}` → 写 `update_task_progress`。Phase 2 起一般不用（strategy_exec 引擎直接写 DB），保留兼容。响应 `ProgressResponse`：`{"ok": true, "task_id": n}`；写失败 → 500 `PROGRESS_WRITE_FAILED`。

### POST /internal/run-sweep-task（202，v123 批次扫描）

请求 `RunSweepTaskRequest`：

| 字段 | 约束 | 说明 |
|---|---|---|
| `user_id` / `strategy_id` / `script_id` / `stock_code` | 同 run-task | 归属信息 |
| `backtest_start_date` / `backtest_end_date` | `^\d{8}$` 必填 | 回测区间 |
| `batch_no` | int ≥1 | 批次号（EvTrade 预建 task 行共享） |
| `param_ranges` | dict，≥1 | `{参数名: {type: int/float/choice/string, start/end/step \| values \| value}}` |
| `metric` | 默认 `"sharpe"` | 必须在白名单 `("sharpe", "total_return", "calmar")` |
| `concurrency` | 1~16，默认 2 | 并发回测数 |
| `period` | 可选，同 run-task | K 线周期 |

model_validator 兜底校验：metric 白名单 + `count_param_ranges` 笛卡尔积 ≤ `SWEEP_HARD_LIMIT`(512)（超限直接 422）。

处理：预连接 publisher → `asyncio.create_task(_run_sweep_batch_background(...), name=f"sweep-batch-{strategy_id}-{batch_no}")`。响应 `RunSweepTaskResponse`：`{"batch_no": n, "total_runs": n, "msg": "sweep accepted, running in background"}`。

### 错误码汇总

| HTTP | code | 场景 |
|---|---|---|
| 401 | MISSING_TOKEN / INVALID_TOKEN | 鉴权失败 |
| 400 | MISSING_DATES / NO_DATA | 回测缺日期 / broker 无数据 |
| 404 | TASK_NOT_FOUND | task 行不存在 |
| 422 | （Pydantic） | 请求体校验失败（含 sweep 超硬上限） |
| 500 | LIVE_START_FAILED / PROGRESS_WRITE_FAILED | 引擎启动 / 进度写失败 |
| 502 | BROKER_ERROR | his_hq 行情服务未响应 |

## 依赖关系

- 上游：EvTrade 后端（HTTP 转发，`X-Internal-Token` header）。
- 下游：`engines/backtrader/`（run_backtest / start_live_runner / run_sweep_batch）、`market_data/hq_history.py`（fetch_his_bars）、`data_access/`（状态/进度写）、`signal/publisher.py`。

## 修改指南

- 新增字段：改 `RunTaskRequest` 等 schema 后必须同步 EvTrade 侧转发代码与前端表单。
- 改错误码：保持 `{code, msg}` 结构，EvTrade 前端按 code 展示提示。
- 新增任务类型：参照 run-sweep-task 模式 —— 请求校验（model_validator 兜底）→ 预连接 publisher → `asyncio.create_task` 后台跑 → 立即返 202。
- 回测后台异常路径必须兜底 `update_task_status(task_id, "failed", ...)`，防止任务永久卡 running。
