# strategy-exec — 策略运行独立服务

> **来源 change**：`2026-08-09-strategy-exec-service`（Backtrader 重构 + 独立服务化）
> **DB schema** 详见 [`data-model/spec.md`](../data-model/spec.md)（strategy_script / strategy_task / strategy_script_audit 共享单库）
> **EvTrade 端 REST API** 详见 [`strategy/spec.md`](../strategy/spec.md) REQ-STRAT-014~017

## Purpose

策略运行能力（回测 + 实盘）是 EvTrade 的独立服务 `strategy_exec/`。它从 EvTrade 主进程剥离，基于 **Backtrader** 重构策略引擎，通过 **RabbitMQ** 推送 buy/sell 信号给 EvTrade 交易端，通过 **HTTP REST** 接收 EvTrade 的启动/停止指令。

**核心约束**：
- **只算不算单**：strategy_exec 只负责"算信号"，风控 / 下单 / 落单 / 持仓推全部留在 EvTrade 交易端（signal_consumer 收到信号后调 `/api/orders/place`）。
- **共享单库**：`strategy_script` / `strategy_task` / `strategy_script_audit` 与 EvTrade 同库（`EVTRADE_DB_URL`），strategy_exec 可写，EvTrade 只读。
- **用户脚本 BREAKING**：v90 的 `on_bar/on_tick/ctx.lib.doorder` 接口废弃，用户脚本须重写为 Backtrader `bt.Strategy.next()` + `self.buy_signal()/self.sell_signal()`（迁移指南见 `docs/strategy-migration-v90-to-bt.md`）。

## Requirements

### REQ-SE-001: 独立部署

StrategyExec MUST 作为独立 Python 服务部署：

- 监听 `STRATEGY_EXEC_HOST` / `STRATEGY_EXEC_PORT`（默认 `0.0.0.0:8001`）
- 独立进程、独立日志、独立 `.env` 配置（`strategy_exec/.env`，不复用 `server/.env`）
- 启动：`python -m strategy_exec.main --port 8001`，或 `strategy_exec/scripts/evctl_strategy_exec.py`（start/stop/status/restart）
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
| 用户脚本自动迁移工具（v90 → Backtrader）| 后续 change（当前仅静态迁移指南 `docs/strategy-migration-v90-to-bt.md`）|
