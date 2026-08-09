# spec-delta: strategy-exec（新增能力 spec）

## Purpose

`strategy_exec/` 是策略运行的独立服务（2026-08-09 strategy-exec-service change）。它从 EvTrade 主进程剥离，基于 Backtrader 重构策略引擎，通过 RabbitMQ 推送信号给 EvTrade 交易端。

不在本 spec 范围：
- 网格策略引擎（`server/services/strategy/quote_consumer.py` + `engine.py`）— 仍属 `strategy/spec.md`
- 风险档位（RiskChecker）— 仍属 `risk-management/spec.md`
- broker RPC 客户端 — 仍属 `rpc-protocol/spec.md`

## Requirements

### REQ-SE-001: 独立部署

StrategyExec MUST 作为独立 Python 服务部署：

- 监听端口 `STRATEGY_EXEC_PORT`（默认 8001）
- 独立进程，独立日志（`/var/log/strategy_exec.log`）
- 独立 `pyproject.toml` 依赖：fastapi / uvicorn / sqlalchemy / pymysql / aio-pika / backtrader / pandas
- 独立 `.env` 配置（不复用 `server/.env`）
- 启动脚本：`strategy_exec/scripts/evctl_strategy_exec.py`（start/stop/status/restart）
- 健康检查：`GET /health` 返 200 + 服务版本

#### Scenario: 独立启动

- **WHEN** `python -m strategy_exec.main --port 8001`
- **THEN** 服务监听 8001
- **AND** `curl http://localhost:8001/health` 返 `{"status": "ok", "version": "0.1.0"}`
- **AND** 服务与 EvTrade 主进程（8000）独立运行

#### Scenario: EvTrade 进程崩溃不影响 strategy_exec

- **WHEN** EvTrade :8000 进程被 kill -9
- **THEN** strategy_exec :8001 继续运行
- **AND** 正在跑的 live task 继续接收行情 + 计算 signal
- **AND** signal 推送 RabbitMQ 成功（EvTrade 死了，signal 进队列等消费）

### REQ-SE-002: 4 internal REST endpoints

strategy_exec 暴露 4 个 internal endpoint（EvTrade 端转发用）：

| Endpoint | 方法 | 路径 |
|---|---|---|
| 启动任务 | POST | `/internal/run-task` |
| 停止任务 | POST | `/internal/stop-task` |
| 查任务状态 | GET | `/internal/tasks/{task_id}/status` |
| 接收 progress 回调 | POST | `/internal/tasks/{task_id}/progress` |

- 所有 endpoint MUST 校验 `X-Internal-Token` header（env `STRATEGY_EXEC_API_TOKEN`）
- 鉴权失败返 401
- 启动/停止返 202 Accepted（异步执行）
- 进度回调返 200 OK

#### Scenario: 启动任务

- **WHEN** EvTrade POST `/internal/run-task` 带 token + `{task_id, user_id, script_id, stock_code, mode, params}`
- **THEN** strategy_exec 立即返 202
- **AND** 后台异步启动 Backtrader 引擎
- **AND** DB strategy_task.status='running'，execution_service='strategy_exec'

#### Scenario: 启动重复任务

- **WHEN** task_id 已在 running 状态
- **THEN** strategy_exec 返 409 Conflict
- **AND** EvTrade 端返 409 给前端

### REQ-SE-003: Backtrader 引擎

策略执行 MUST 基于 **Backtrader**（业界标准回测/实盘框架）：

- 回测：`bt.Cerebro.run()` 同步跑完，写 `strategy_task.backtest_result` + `pnl` + `trades_count`
- 实盘：`bt.Cerebro.run()` 异步启动，订阅 hqserver WS tick → 调用户脚本 `next()` → 生成 signal
- 数据源：
  - 历史 K 线：从 broker his_hq RabbitMQ 队列拉取
  - 实时 tick：从 `ws://hqserver:8765/quota.broadcast` 直连订阅
- 用户脚本接口：继承 `ProjectStrategy(bt.Strategy)`（项目适配层），提供 `buy_signal()` / `sell_signal()` 方法

#### Scenario: 回测金叉策略

- **WHEN** 用户脚本 `class MyStrategy(ProjectStrategy): next()` 实现双均线金叉
- **AND** 跑回测 20260101 ~ 20260630, period='1d', stock='600519.SH'
- **THEN** Backtrader.cerebro.run() 跑完
- **AND** 写 `strategy_task.backtest_result`（含 trades / equity_curve / signals）
- **AND** 写 `strategy_task.pnl` / `trades_count`
- **AND** 写 `strategy_script_audit` 每条 BUY/SELL 信号

#### Scenario: 实盘订阅 tick

- **WHEN** LiveRunner 启动 task_id=123
- **THEN** 连 `ws://hqserver:8765/quota.broadcast`，订阅 stock_code='600519.SH'
- **AND** 收到 tick → 累积 1m K 线 → 调用户脚本 `next()`
- **AND** 用户脚本调 `self.buy_signal()` → signal_publisher.publish_signal()

### REQ-SE-004: RabbitMQ 信号推送

策略执行生成的 signal MUST 通过 RabbitMQ 推送给 EvTrade：

- exchange: `EVTRADE_STRATEGY_EXCHANGE_NAME`（topic, durable=True）
- queue: `EvTrade.StrategySignal`（durable=True, 由 EvTrade signal_consumer 订阅）
- routing_key: `stock_code`（如 `600519.SH`）
- payload schema（JSON）：

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

- MUST 用 **publisher confirms**（confirm_timeout=5s）
- 失败重试 3 次
- 推送失败 → 写 `strategy_task.error_msg` + `status='failed'`

#### Scenario: 推送 BUY signal

- **WHEN** 用户脚本调 `self.buy_signal(price=100, volume=100)`
- **THEN** signal_publisher.publish() 发到 `strategy.exchange`，routing_key='stock_code'
- **AND** broker confirm 在 5s 内返 ack
- **AND** 写 `strategy_script_audit` 一条 `type='BUY'` 记录

#### Scenario: 推送失败兜底

- **WHEN** RabbitMQ broker 不可达
- **THEN** publisher 等待 5s 超时
- **AND** 重试 3 次（每次间隔指数退避 1s/2s/4s）
- **AND** 仍失败 → 写 `strategy_task.error_msg='signal 推送失败: broker timeout'`
- **AND** 写 `strategy_task.status='failed'`

### REQ-SE-005: 用户脚本接口（Backtrader 适配层）

用户脚本 MUST 继承 `ProjectStrategy(bt.Strategy)`：

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
                msg=f'金叉'
            )
```

提供方法：
- `self.buy_signal(price, volume, *, price_type='limit', indicators={}, msg='')` → 推送 BUY signal
- `self.sell_signal(price, volume, *, price_type='limit', indicators={}, msg='')` → 推送 SELL signal
- `self.notify_signal_published(signal_id, ok)` → 推送成功/失败回调（可选）
- `self.get_position()` → 查本地持仓（backtrader broker 的 self.position.size）

#### Scenario: 用户脚本 next() 触发 buy_signal

- **WHEN** Backtrader 每根 bar 调 `next()`
- **AND** `self.data.close[0] > self.sma_slow[0]`
- **THEN** 用户调 `self.buy_signal(price=1680.5, volume=100)`
- **AND** adapter 内部调 signal_publisher.publish_signal()
- **AND** RabbitMQ 推送成功
- **AND** 写 strategy_script_audit 一条 type=BUY 记录

### REQ-SE-006: 沙箱安全约束

用户脚本 MUST 在受限沙箱中执行：

- 动态 import（`importlib.util.spec_from_file_location`）
- **禁止**导入：`os.system` / `subprocess` / `open` / `socket` / `requests`（网络白名单）
- **允许**：`backtrader` / `numpy` / `pandas` / `math` / 用户脚本本身的 imports
- 不允许写文件到沙箱外
- 默认模板：`strategy_exec/strategy_exec/templates/default_bt_strategy.py`

#### Scenario: 用户脚本尝试访问网络

- **WHEN** 用户脚本 `import requests; requests.get('http://evil.com')`
- **THEN** sandbox loader 检测 import 黑名单
- **AND** 抛 `SandboxViolationError`
- **AND** task status='failed', error_msg='禁止 import requests'

### REQ-SE-007: 数据模型扩展（strategy_task 3 字段）

DB `strategy_task` 表加 3 字段（migration `2026-08-09-strategy-task-exec-fields.py`）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `execution_service` | String(16) | `'evtrade'` | 任务执行服务标识（'evtrade' / 'strategy_exec'）|
| `execution_pid` | Integer | NULL | strategy_exec 实例进程 pid（用于排查）|
| `version` | Integer | 0 | **乐观锁**，UPDATE 时 `WHERE version=:v` 防 lost update |

- 写竞争：`strategy_exec` 写 `progress` + EvTrade `signal_consumer` 写 `status` —— 用 version 字段乐观锁
- 冲突：3 次重试仍失败 → 抛 `OptimisticLockError`，写 error_msg

#### Scenario: 双服务并发写 strategy_task

- **WHEN** strategy_exec 写 progress (version=0→1)
- **AND** 同时 EvTrade signal_consumer 写 status (version=0→1)
- **THEN** 后到的写 `WHERE version=0` 不匹配
- **AND** 重试读最新 version，再写 `WHERE version=1`
- **AND** 最坏 case: 写失败 3 次 → 抛 OptimisticLockError → 写 error_msg

## Cross References

- 网格策略引擎（仍是 EvTrade 进程内）：`strategy/spec.md` REQ-STRAT-001~013
- 风控（不在 strategy_exec）：`risk-management/spec.md`
- 配置：`configuration/spec.md` REQ-CFG-XXX（4 个新 env）
- 部署：`dev-process-control/spec.md` §"进程管控"

## Out of Scope（Future / 后跟 change）

| 项 | 时机 |
|---|---|
| 网格策略独立化 | 后续 change |
| strategy_exec HA（多实例 + 选举）| 后续 change |
| 多策略组合优化器 | 后续 change（Backtrader 支持，1-2 天工作量）|
| 策略回测报告 Web 渲染 | 后续 change（独立 BI 模块）|
| v90 旧引擎兼容适配器（让旧脚本继续跑）| **不在规划** —— BREAKING，用户需重写 |
| 用户脚本自动迁移工具（v90 → Backtrader）| 后续 change（提供 best-effort 转换工具）|