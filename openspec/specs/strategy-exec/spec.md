# strategy-exec — 策略运行独立服务

> **来源 change**：
> - `2026-08-09-strategy-exec-service`（Backtrader 重构 + 独立服务化）
> - `2026-08-10-strategy-params-sweep-best-live`（v122，schema 注入 + sweep 引擎 + live 接 best_params）— 见 REQ-SE-008 / REQ-SE-009
> **DB schema** 详见 [`data-model/spec.md`](../data-model/spec.md)（strategy_script / strategy_task / strategy_script_audit 共享单库）
> **EvTrade 端 REST API** 详见 [`strategy/spec.md`](../strategy/spec.md) REQ-STRAT-014~017

## Purpose

策略运行能力（回测 + 实盘）是 EvTrade 的独立服务 `strategy_exec/`。它从 EvTrade 主进程剥离，基于 **Backtrader** 重构策略引擎，通过 **RabbitMQ** 推送 buy/sell 信号给 EvTrade 交易端，通过 **HTTP REST** 接收 EvTrade 的启动/停止指令。

**核心约束**：
- **只算不算单**：strategy_exec 只负责"算信号"，风控 / 下单 / 落单 / 持仓推全部留在 EvTrade 交易端（signal_consumer 收到信号后调 `/api/orders/place`）。
- **共享单库**：`strategy_script` / `strategy_task` / `strategy_script_audit` 与 EvTrade 同库（`EVTRADE_DB_URL`），strategy_exec 可写，EvTrade 只读。
- **用户脚本 BREAKING**：v90 的 `on_bar/on_tick/ctx.lib.doorder` 接口废弃，用户脚本须重写为 Backtrader `bt.Strategy.next()` + `self.buy_signal()/self.sell_signal()`（迁移指南可查 git 历史 `docs/strategy-migration-v90-to-bt.md`）。

## Requirements

### REQ-SE-001: 独立部署

StrategyExec MUST 作为独立 Python 服务部署：

- 监听 `STRATEGY_EXEC_HOST` / `STRATEGY_EXEC_PORT`（默认 `0.0.0.0:8001`）
- 独立进程、独立日志、独立 `.env` 配置（`strategy_exec/.env`，不复用 `server/.env`）
- 启动：`python -m strategy_exec.main --port 8001`，或 `uv run python ./scripts/evctl.py start|restart|stop strategy_exec`（已集成进 evctl.py，无独立 controller 脚本）
- 健康检查：`GET /health` 返 200 + 服务版本
- **依赖**：复用 EvTrade 根 `.venv`（pydantic v2 + `pydantic-settings`）。曾规划独立 `pyproject.toml`/`Dockerfile`，2026-08-09 决策改为复用根 .venv，两者已删除（commit `154a36b`）

#### Scenario: 独立启动

- **WHEN** `python -m strategy_exec.main --port 8001`
- **THEN** 服务监听 8001
- **AND** `curl http://localhost:8001/health` 返 `{"status": "ok", "version": "..."}`
- **AND** 服务与 EvTrade 主进程（8000）独立运行

#### Scenario: EvTrade 进程崩溃不影响 strategy_exec

- **WHEN** EvTrade :8000 进程被 kill
- **THEN** strategy_exec :8001 继续运行
- **AND** 正在跑的 live task 继续接收行情 + 计算 signal
- **AND** signal 推送 RabbitMQ 成功（EvTrade 死了，signal 进队列等消费）

### REQ-SE-002: 4 internal REST endpoints

strategy_exec 暴露 4 个 internal endpoint（EvTrade 端转发用）：

| Endpoint | 方法 | 路径 | 成功响应 |
|---|---|---|---|
| 启动任务 | POST | `/internal/run-task` | 202 Accepted（异步执行）|
| 停止任务 | POST | `/internal/stop-task` | 200 |
| 查任务状态 | GET | `/internal/tasks/{task_id}/status` | 200 |
| 接收 progress 回调 | POST | `/internal/tasks/{task_id}/progress` | 200 |

- **鉴权**：`STRATEGY_EXEC_API_TOKEN` 配置时，所有 `/internal/*` MUST 校验 `X-Internal-Token` header，失败返 401；token 为空 = 局域网部署**不鉴权**（直接放行）
- `run-task` 请求体：`task_id / user_id / script_id / stock_code / mode(backtest|live) / params / period / backtest_start_date / backtest_end_date / fields`
- **backtest 模式**：`backtest_start_date` + `backtest_end_date` 必填（`MISSING_DATES` 400）；先拉历史 K 线再后台异步执行
- **live 模式**：启动 LiveRunner，立即返 202

#### Scenario: 启动任务

- **WHEN** EvTrade POST `/internal/run-task` 带 token + `{task_id, user_id, script_id, stock_code, mode, params}`
- **THEN** strategy_exec 立即返 202 Accepted
- **AND** 后台异步启动 Backtrader 引擎
- **AND** DB strategy_task.status='running'，execution_service='strategy_exec'

#### Scenario: 回测缺日期被拒

- **WHEN** POST `/internal/run-task` mode='backtest' 但缺 `backtest_start_date` 或 `backtest_end_date`
- **THEN** 返 400，`{"code": "MISSING_DATES", "msg": "回测模式缺少必填参数: ...（格式 YYYYMMDD）"}`

#### Scenario: 历史行情服务不可用

- **WHEN** backtest 模式拉历史 K 线时 broker his_hq 服务未响应（RabbitMQ 超时）
- **THEN** 返 502，`{"code": "BROKER_ERROR", "msg": "broker his_hq 行情服务未响应: ... 请确认 QMT 端历史行情(his_hq)服务已启动..."}`

#### Scenario: 任务不存在

- **WHEN** GET `/internal/tasks/{task_id}/status` 而 task_id 不存在
- **THEN** 返 404，`{"code": "TASK_NOT_FOUND"}`

### REQ-SE-003: Backtrader 引擎

策略执行 MUST 基于 **Backtrader**（业界标准回测/实盘框架），位于 `strategy_exec/strategy_exec/engines/backtrader/`：

- **回测**：`run_backtest()` 在 `asyncio.to_thread` 中同步跑 `bt.Cerebro.run()`，逐 bar 调用户脚本 `next()`，结束后写 `strategy_task.backtest_result`（含 `signal_log` / `progress_log` / `trades` / `equity_curve` / `win_rate` / `pnl` / `pnl_pct`）+ `pnl` / `trades_count` / `best_params`，并按 phase 写 `progress`
- **实盘**：`LiveRunner` 异步启动，订阅 hqserver WS tick → 累积 1m K 线 → 调用户脚本 `next()` → 生成 signal
- **数据源**：
  - 历史 K 线：`market_data/hq_history.py::fetch_his_bars`，走 broker his_hq RabbitMQ（`quota_his.exchange` + `EvTrade.ReqHisHq` 队列，`EVTRADE_HIS_HQ_*` env），超时 30s
  - 实时 tick：`market_data/hq_ws_client.py` 直连 `HQ_WS_URL`（默认 `ws://127.0.0.1:8765/quota.broadcast`），自动重连（1000ms 起步，最大 30s）
- **用户脚本接口**：继承 `ProjectStrategy(bt.Strategy)`（见 REQ-SE-005）
- 默认模板：`strategy_exec/strategy_exec/templates/default_bt_strategy.py`（双均线策略）

#### Scenario: 回测金叉策略

- **WHEN** 用户脚本 `class MyStrategy(ProjectStrategy): next()` 实现双均线金叉
- **AND** 跑回测 `20260101 ~ 20260630`, period='1d', stock='600519.SH'
- **THEN** Backtrader `cerebro.run()` 跑完
- **AND** 写 `strategy_task.backtest_result`（含 trades / equity_curve / signal_log）
- **AND** 写 `strategy_task.pnl` / `trades_count` / `best_params`
- **AND** 每条 BUY/SELL 信号写 `strategy_script_audit`

#### Scenario: 实盘订阅 tick

- **WHEN** LiveRunner 启动 task_id=123
- **THEN** 连 hqserver WS `quota.broadcast`，订阅 stock_code='600519.SH'
- **AND** 收到 tick → 累积 1m K 线 → 调用户脚本 `next()`
- **AND** 用户脚本调 `self.buy_signal()` → RabbitMQ 推送 signal

#### Scenario: live_signals 环形缓冲

- **WHEN** live task 运行中 signal 持续产生
- **THEN** strategy_task.live_signals 数组限 500 条（超出覆盖最早）
- **AND** 每 5s flush 一次到 DB（`append_live_signals`，非逐条写）

### REQ-SE-004: RabbitMQ 信号推送

策略执行生成的 signal MUST 通过 RabbitMQ 推送给 EvTrade 交易端（`signal/publisher.py`）：

- exchange：`EVTRADE_STRATEGY_EXCHANGE_NAME`（默认 `strategy.exchange`，topic，durable=True）
- queue：`EvTrade.StrategySignal`（durable，由 EvTrade `server/services/strategy/signal_consumer.py` 订阅）
- routing_key：`stock_code`（如 `600519.SH`）
- 消息：PERSISTENT delivery、`message_id=trace_id`、headers 带 `task_id/user_id/script_id/signal_type`
- **publisher confirms**（`confirm_timeout=EVTRADE_STRATEGY_PUBLISH_CONFIRM_TIMEOUT`，默认 5s）
- 失败重试 `EVTRADE_STRATEGY_PUBLISH_RETRIES`（默认 3）次，指数退避 1s/2s/4s
- 重试仍失败 → 抛 `SignalPublishError` → caller 写 `strategy_task.error_msg` + `status='failed'`

payload schema（JSON）：

```json
{
  "task_id": 123,
  "user_id": 6,
  "script_id": "ma5_e2e",
  "signal_type": "BUY",
  "stock_code": "600519.SH",
  "price": 1680.5,
  "volume": 100,
  "price_type": "limit",
  "indicators": {"ma5": 1670.0, "ma20": 1650.0},
  "ts": "2026-08-09T10:30:15.123456",
  "trace_id": "uuid-v4",
  "msg": "金叉, ma5=1670"
}
```

#### Scenario: 推送 BUY signal

- **WHEN** 用户脚本调 `self.buy_signal(price=100, volume=100)`
- **THEN** signal_publisher.publish() 发到 `strategy.exchange`，routing_key='stock_code'
- **AND** broker confirm 在 5s 内返 ack
- **AND** 写 `strategy_script_audit` 一条 `type='BUY'` 记录

#### Scenario: 推送失败兜底

- **WHEN** RabbitMQ broker 不可达
- **THEN** publisher 等待 confirm_timeout 超时
- **AND** 重试 3 次（指数退避 1s/2s/4s）
- **AND** 仍失败 → 抛 SignalPublishError
- **AND** task status='failed'，error_msg 记录推送失败

### REQ-SE-005: 用户脚本接口（Backtrader 适配层）

用户脚本 MUST 继承 `ProjectStrategy(bt.Strategy)`（`engines/backtrader/adapter.py`）：

```python
import backtrader as bt
from strategy_exec.engines.backtrader.adapter import ProjectStrategy

class MyStrategy(ProjectStrategy):
    params = (('fast', 5), ('slow', 20), ('qty', 100))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)

    def next(self):
        if not self.position and self.data.close[0] > self.sma_slow[0]:
            self.buy_signal(
                price=self.data.close[0],
                volume=self.p.qty,
                indicators={'ma5': self.sma_fast[0]},
                msg='金叉'
            )
```

提供方法：
- `self.buy_signal(price, volume, *, price_type='limit', indicators={}, msg='')` → 推送 BUY signal，成功返 trace_id，失败返 None
- `self.sell_signal(price, volume, *, price_type='limit', indicators={}, msg='')` → 推送 SELL signal
- `self.notify_signal_published(signal_id, ok)` → 推送成功/失败回调（可选，默认 log 一行）
- `self.get_position()` → 查本地持仓（Backtrader broker `self.position.size`）
- `self.get_cash()` → 查本地现金（`self.broker.getcash()`）

- stock_code 来自数据源名 `self.data._name`；task 元数据（task_id/user_id/script_id/mode）由 Engine 在 `addstrategy` 前注入 `_set_task_meta()`
- Backtrader `next()/init()` 等标准方法不受影响
- v126 母单路径：`Signal` 额外字段 `parent_task_id: Optional[int] = None` + `strategy_name: str = ""`（母单 start 时透传，用于 signal_consumer 归因 `orders.task_id`/`user_def`/`strategy_type=2`）
- 旧 v122/v123 sweep 路径：`parent_task_id=None` + `strategy_name=""` 默认值兼容，行为不变

#### Scenario: 用户脚本 next() 触发 buy_signal

- **WHEN** Backtrader 每根 bar 调 `next()`
- **AND** `self.data.close[0] > self.sma_slow[0]`
- **THEN** 用户调 `self.buy_signal(price=1680.5, volume=100)`
- **AND** adapter 内部调 signal_publisher.publish_signal()
- **AND** RabbitMQ 推送成功
- **AND** 写 strategy_script_audit 一条 type=BUY 记录

### REQ-SE-006: 沙箱安全约束

用户脚本 MUST 在受限沙箱中执行（`sandbox/loader.py`）：

- **AST 静态扫描**（exec 前）：检测危险调用——`os.system/os.popen/os.execv/subprocess.*/socket.*/urllib.*/http.client.*/eval/exec/compile/__import__`，命中即抛 `SandboxViolationError`
- **受限 namespace**：自定义 `__import__` 拦截 + 白名单模块注入
- **禁止导入**：`os` / `subprocess` / `socket` / `requests` / `urllib` / `http.client`（`SANDBOX_BLOCKED_MODULES`，可配）
- **允许导入**：`backtrader` / `numpy` / `pandas` / `math` / `json` / `datetime` / `typing`（`SANDBOX_ALLOWED_MODULES`，可配）+ 注入的 `ProjectStrategy`
- 用户脚本 MUST 定义至少一个 `ProjectStrategy` 子类（找不到 → `ValueError`）
- 默认模板：`strategy_exec/strategy_exec/templates/default_bt_strategy.py`

#### Scenario: 用户脚本尝试访问网络

- **WHEN** 用户脚本 `import requests; requests.get('http://evil.com')`
- **THEN** sandbox loader 检测 import 黑名单
- **AND** 抛 `SandboxViolationError`
- **AND** task status='failed'，error_msg 记录违规信息

#### Scenario: 用户脚本未定义策略类

- **WHEN** 用户脚本源码不含任何 `ProjectStrategy` 子类
- **THEN** loader 抛 `ValueError`（"用户脚本未定义任何 ProjectStrategy 子类"）

### REQ-SE-007: 数据模型扩展（strategy_task 3 字段）

DB `strategy_task` 表加 3 字段（migration `2026-08-09-strategy-task-exec-fields.py`）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `execution_service` | String(16) | `'evtrade'` | 任务执行服务标识（'evtrade' / 'strategy_exec'）|
| `execution_pid` | Integer | NULL | strategy_exec 实例进程 pid（排查用）|
| `version` | Integer | 0 | **乐观锁**，UPDATE 时 `WHERE version=:v` 防 lost update |

- **写竞争**：strategy_exec 写 `progress`/`live_signals`/`status` + EvTrade `signal_consumer` 写 `status`/`order_no` —— 都用 `version` 乐观锁
- 实现：`data_access/strategy_task.py` 的 `update_task_status` / `update_task_progress` / `append_live_signals` 全部 `UPDATE ... WHERE id=:i AND version=:v`，`rowcount=0` → 冲突，重试 3 次（每次读最新 version）
- 重试仍失败 → 抛 `OptimisticLockError` → 写 error_msg
- `write_audit`：写 `strategy_script_audit`（`phase` = backtest/live 上下文 + `trigger_type` = BUY/SELL/SIGNAL/STOP/TP/INFO）

#### Scenario: 双服务并发写 strategy_task

- **WHEN** strategy_exec 写 progress (version=0→1)
- **AND** 同时 EvTrade signal_consumer 写 status (version=0→1)
- **THEN** 后到的写 `WHERE version=0` 不匹配（rowcount=0）
- **AND** 重试读最新 version，再写 `WHERE version=1`
- **AND** 最坏 case: 写失败 3 次 → 抛 OptimisticLockError → 写 error_msg

### REQ-SE-008: 参数扫描（sweep backtest）

> **来源 change**：`2026-08-10-strategy-params-sweep-best-live`（v122）
> **设计**：`openspec/changes/2026-08-10-strategy-params-sweep-best-live/design.md` §2

StrategyExec MUST 支持一次提交多组参数组合的回测，并按指定指标排序挑 best。

#### API

新增 endpoint：

```
POST /internal/run-sweep-task
```

Request：

```jsonc
{
    "user_id": 6,
    "script_id": "mas_v1",
    "stock_code": "000001.SZ",
    "backtest_start_date": "20250101",
    "backtest_end_date": "20260701",
    "param_grid": {
        "fast": [3, 5, 7, 10],
        "slow": [15, 20, 30, 60]
    },
    "metric": "sharpe",
    "select_top_n": 1,
    "concurrency": 2
}
```

Response（202 Accepted，异步）：

```jsonc
{
    "sweep_id": "abc123...",
    "total_runs": 16,
    "summary_task_id": 42
}
```

#### 行为约束

- **笛卡尔积**：`iter_param_grid(param_grid)` 生成所有组合；若某字段仅 1 个值（= 未扫描），该字段不参与笛卡尔积
- **大小校验**：
  - 软警告 64 组合（log warning，不阻断）
  - 硬拒绝 512 组合（抛 `ValueError`，EvTrade 端返 400）
- **并发控制**：`asyncio.Semaphore(concurrency)` 控制同时跑的 backtest 数（默认 2）
- **失败容错**：任一组合失败 → 该 task `status='failed'`，其余继续；sweep_summary 记录 N 成功 M 失败，best_params 仅从成功里挑
- **指标**：`metric` ∈ {`sharpe`, `total_return`, `calmar`}
  - `sharpe` 取 `SharpeRatio` analyzer
  - `total_return` = `pnl / initial_cash`（默认 cash=100000）
  - `calmar` = `total_return / max_drawdown`（`max_drawdown=0` 返 None，避免除零）
- **持久化**：
  - 每个组合 = 独立 `strategy_task` row，共享 `sweep_id`
  - 额外生成 1 个 summary task（`sweep_id=sweep_id`, `sweep_total=1`），其 `best_params` = top1 组合 params；`backtest_result.sweep_results` = 全部组合的 metric 排序数组（含失败的 `'failed'` 标记）；`backtest_result.best_metric_value` = top1 的 metric 值（顶层冗余字段）
- **K 线共享**：1 次 `fetch_his_bars` 拉全区间，N 个组合共用（同 sweep 内）

#### Scenario: 16 组合 sweep 全成功

- **WHEN** POST /internal/run-sweep-task with `param_grid = {fast: [3,5,7,10], slow: [15,20,30,60]}`（16 组合）
- **THEN** 创建 16 个 task（sweep_id 共享）+ 1 个 summary task
- **AND** 全部 status='finished'
- **AND** summary task.best_params = 排序 top1 组合
- **AND** summary task.backtest_result.sweep_results = 16 行 metric 排序数组（降序）

#### Scenario: 部分组合失败

- **WHEN** sweep 中 2 个组合 backtest 抛错
- **THEN** 这 2 个 task status='failed'，error_msg 记录
- **AND** 其余 14 个 task 正常 finished
- **AND** summary task.best_params 来自 14 个成功的（不选失败的）
- **AND** summary task.status 仍 'finished'（不是 failed），error_msg 为空

#### Scenario: 全失败兜底

- **WHEN** sweep 全部组合 backtest 抛错
- **THEN** summary task.status='failed'
- **AND** summary task.best_params=null，best_metric_value=null
- **AND** sweep_results 数组中所有项 status='failed'

#### Scenario: grid > 512 硬拒绝

- **WHEN** `count_grid_size(param_grid) > 512`
- **THEN** 抛 `ValueError("grid size N 超过硬上限 512")`
- **AND** EvTrade 端返 400 + `{"code": "GRID_TOO_LARGE", "msg": "..."}`
- **AND** 不创建任何 strategy_task row

#### Scenario: broker 无 K 线

- **WHEN** `fetch_his_bars()` 返空（broker his_hq 异常或股票无数据）
- **THEN** 抛 `RuntimeError("broker 未返回 K 线")`
- **AND** 不创建任何 strategy_task row

### REQ-SE-009: 实盘任务接历史 best_params

> **来源 change**：`2026-08-10-strategy-params-sweep-best-live`（v122）

实盘任务的 `params` MUST 可源自任一历史 backtest task（含 sweep summary task）的 `best_params`。

#### 数据契约

启动实盘 task 时，校验：

- `task.params` 的 key 集合 ⊆ 当前 `script_id` 的 `params_schema` 的 key 集合
- 任一 key 缺失（schema 已删字段） → 启动前返 400，msg 列出缺失 key
- 所有 key 都已存在 → 启动 live，行为与原一致（live runner 用 `cls.p.<key>=<value>` 计算信号）

#### API 扩展（EvTrade 转发层）

新增查询端点（EvTrade `GET /api/strategy/tasks` 新 query params）：

```
GET /api/strategy/tasks
  ?script_id=mas_v1
  &status=finished
  &has_best_params=1   // 限定 best_params 非空
  &limit=50            // 默认 50，最大 200
```

Response TaskOut 扩展字段：

```jsonc
{
    "task_id": 42,
    "script_id": "mas_v1",
    "sweep_id": "abc123...",
    "sweep_metric": "sharpe",
    "sweep_total": 16,
    "best_params": {"fast": 7, "slow": 30, "qty": 100, "rsi_period": 14},
    "backtest_metric_value": 1.82,
    "finished_at": "2026-08-10T15:30:00",
    "mode": "backtest"
}
```

- `backtest_metric_value` 来源：
  - 单 run：`backtest_result.sharpe`（或所选 metric）
  - sweep summary：`backtest_result.best_metric_value`（顶层冗余）
- 前端用此查询渲染 "从历史回测选参数" 弹窗

#### Scenario: live 启动用 sweep 的 best_params

- **WHEN** 用户在 ScriptTask 启实盘，选 task #42（sweep summary，best: fast=7, slow=30）
- **THEN** POST /api/strategy/tasks with `mode='live', params={fast:7, slow:30, qty:100, rsi_period:14}`
- **AND** EvTrade 转发到 strategy_exec 启 live runner
- **AND** live runner 用 `cls.p.fast=7, cls.p.slow=30` 计算信号（Backtrader 元类自动注入）

#### Scenario: best_params 引用了已删字段

- **WHEN** schema 升级，删了 `rsi_period` 字段；但旧 task #42 的 best_params 还含 `rsi_period=14`
- **AND** 用户想用 task #42 的 best 启 live
- **THEN** 启动前校验 `best_params.key ⊆ current_schema.key`，发现 `rsi_period` 多余
- **AND** 返 400：`"best_params 包含 schema 已删除字段: rsi_period; 请改用其他回测或手动重选"`

#### Scenario: live runner 接收 schema 注入

- **WHEN** LiveRunner 启动 task，`task.params` 含 fast/slow/qty/rsi_period
- **AND** script 的 `params_schema` 含同名 4 字段
- **THEN** `load_strategy_class(code, ProjectStrategy, params_schema=params_schema)` 注入 schema 到 `cls.params`
- **AND** Backtrader 元类把 `task.params` 的值注入到 `cls.p.fast` / `cls.p.slow` / 等
- **AND** 用户脚本 `next()` 读 `self.p.fast` 等得到正确值

> **schema 注入机制**（loader 严格模式）：code 声明的 `params` key 集合 MUST = schema key 集合，否则 `ValueError`（不允许代码 + schema 双源）。v121+ 目标：code 不再声明 `params = (...)`，schema 为唯一契约。`params_schema=None` 时走老逻辑（不注入，backward compat）。

### REQ-SE-010: 母单 live metadata 透传（v126）

> **来源 change**：`2026-08-11-strategy-order-design`（v126）

EvTrade 母单路径下，`LiveRunner` MUST 接受并透传母单元数据，使 signal 链路可在 EvTrade `signal_consumer` 端归因到对应母单。

#### API 扩展

`POST /internal/run-task` Request 增加可选字段：

```jsonc
{
  "task_id": 42,
  "user_id": 1,
  "script_id": "mas_v1",
  "stock_code": "600519.SH",
  "mode": "live",
  "params": {...},
  "parent_task_id": 5555,    // v126 NEW: 母单 task_id
  "strategy_name": "双均线"   // v126 NEW: 策略名 (写到 orders.user_def)
}
```

- 旧 v122/v123 sweep 路径不传这 2 字段 → 走 `Optional[int] = None` / `str = ""` 默认值，行为完全不变
- 母单路径必带 `parent_task_id`（v126 decision D）；缺则 EvTrade signal_consumer 报 `INVALID_PARENT_TASK` 业务错 ack 不重试

#### LiveRunner 内部透传链

`start_live_runner(parent_task_id, strategy_name, ...)` → `LiveRunner.__init__` → `_set_task_meta` → `self._parent_task_id` / `self._strategy_name` → `_publish` 构造 `Signal(parent_task_id=..., strategy_name=..., ...)`。

#### Scenario: 母单 start → live runner 启动 + payload 含 metadata

- **WHEN** EvTrade `POST /strategy-orders/1/start` 转发到 `strategy_exec /internal/run-task`
- **AND** payload 含 `parent_task_id=5555, strategy_name='双均线'`
- **THEN** LiveRunner 实例化后 `runner._parent_task_id == 5555`
- **AND** 用户脚本 `next()` 触发 `buy_signal` → publish 到 RabbitMQ 的 payload 含 `parent_task_id=5555, strategy_name='双均线'`

#### Scenario: 旧 sweep live 路径 metadata 默认值

- **WHEN** EvTrade `POST /strategy/tasks` with `mode='live'`（旧 v122 sweep best_params 启 live）
- **THEN** 不传 `parent_task_id` / `strategy_name`
- **AND** LiveRunner `_parent_task_id is None` + `_strategy_name == ''`
- **AND** publish payload 同上，EvTrade signal_consumer 按 v122 旧逻辑处理（task_id=None, strategy_type=1 兼容）

## Cross References

- EvTrade 端 script-strategy REST API / 数据模型 / 前端：`strategy/spec.md` REQ-STRAT-014~017（CRUD 仍在 EvTrade，仅**运行引擎**迁到本服务）
- ~~网格策略引擎（仍在 EvTrade 进程内）~~ → **2026-08-10 已删除**（commit `aa70dae`；`strategy/spec.md` REQ-STRAT-001~013 已标记下线）
- 风控（不在 strategy_exec）：`risk-management/spec.md`
- 配置 env：`configuration/spec.md` REQ-CFG-XXX（`STRATEGY_EXEC_*` / `EVTRADE_STRATEGY_*` / `EVTRADE_HIS_HQ_*` / `HQ_WS_URL` / `SANDBOX_*`）
- 信号消费（EvTrade 端下单）：`server/services/strategy/signal_consumer.py` + `push/spec.md`
- 部署：`dev-process-control/spec.md`

## Out of Scope（Future / 后跟 change）

| 项 | 时机 |
|---|---|
| ~~网格策略独立化~~ | 作废（2026-08-10 网格引擎已整体删除）|
| strategy_exec HA（多实例 + 选举）| 后续 change |
| 多策略组合优化器 | 后续 change（Backtrader 支持）|
| 策略回测报告 Web 渲染 | 后续 change（独立 BI 模块）|
| 用户脚本自动迁移工具（v90 → Backtrader）| 后续 change（静态迁移指南可查 git 历史）|

## iQuant / QMT 适配库（2026-08-25）

### REQ-SE-011: iquant 错误处理禁止裸 except

The `iquant/*.py` 适配库（`runtime_trdapi_rel.py` / `quota_his.py`）SHALL NOT 使用裸 `except:` 子句吞噬 `KeyboardInterrupt` / `SystemExit`。Drain-queue 模式

```python
while not Q.empty():
    try:
        Q.get_nowait()
    except:   # ❌ 禁止
        break
```

MUST 改写为

```python
while not Q.empty():
    try:
        Q.get_nowait()
    except queue.Empty:
        break
```

`import queue` MUST 已在模块顶部。

#### Scenario: drain queue 正确捕获 Empty

- **WHEN** shutdown path 在 `iquant/runtime_trdapi_rel.py` 或 `iquant/quota_his.py` 中排空 `GLOBAL_REQ_QUEUE` / `GLOBAL_ANS_QUEUE`
- **THEN** 队列空时退出仅捕获 `queue.Empty`；`KeyboardInterrupt` / `SystemExit` 正常向上传播

### REQ-SE-012: iquant 行为零变更（2026-08-25）

This change SHALL NOT modify any of:
- 策略执行热路径（signal 接收 / 下单 / 行情消费）
- RPC 客户端协议（msgpacket / xtconstant）
- MQ 线程生命周期（start / stop / join / daemon flag）
- 沙箱与回测行为

仅做 except 收窄（裸 → `queue.Empty`）。
