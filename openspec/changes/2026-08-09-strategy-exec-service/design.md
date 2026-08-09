# design.md — strategy-exec-service 架构设计

> 配套 [proposal.md](./proposal.md)。本文档定义：架构、数据流、RabbitMQ 拓扑、API 契约、数据模型变更、迁移路径。

## 1. 目标架构

### 1.1 当前架构（before）

```
┌─────────────────────────────────────────────────────────────────┐
│  EvTrade 后端 (FastAPI :8000) — 单一进程                         │
│                                                                  │
│  HTTP /api/script-strategy/*  ───► endpoints.py                 │
│                                          │                       │
│                                          ▼                       │
│                                   service.py (999 行)           │
│                                          │                       │
│            ┌─────────────────────────────┼────────────────┐     │
│            │                             │                │     │
│            ▼                             ▼                ▼     │
│      runtime/backtest.py          runtime/live.py     runtime/  │
│      (threading)                  (asyncio + WS)      sandbox.py│
│            │                             │                │     │
│            └──────► strategy_script ─────┴────► strategy_task ──│
│                                                                  │
│      lib/trading.py.doorder ──► server.api.orders.ord_stk       │
│                                  (同进程 RPC + DB)              │
│                                                                  │
│      lib/trading.py.docancel ──► server.rpc.client.cancel_order │
│                                                                  │
│      LiveRunner ──WS ws://127.0.0.1:8000/ws/quote_update─────   │
│                       (内部 token 鉴权, quote 后端转发)          │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 目标架构（after）

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (Vue3 :50998)                                            │
│      │                                                            │
│      │ HTTP /api/script-strategy/* (不变)                          │
│      │                                                            │
└──────┼────────────────────────────────────────────────────────┐  │
       │                                                        │  │
       ▼                                                        │  │
┌──────────────────────────────────────────────────┐             │  │
│  EvTrade 后端 (FastAPI :8000)                    │             │  │
│                                                  │             │  │
│  endpoints.py  (forwarding)                      │             │  │
│    POST /tasks/{id}/run  ────► HTTP转发 ────┐    │             │  │
│    POST /tasks/{id}/stop ────► HTTP转发 ────┤    │             │  │
│                                             │    │             │  │
│  signal_consumer.py (新增) ◄── RabbitMQ ◄────┴────┼──┐         │  │
│    │ 收 signal  ──► POST /api/orders/place    │    │         │  │
│    │                                          │    │         │  │
│  ws_manager.broadcast("task_progress_update") │    │         │  │
│    │  ──────► ScriptTask.vue ◄────────────────│    │         │  │
│                                                  │             │  │
└──────────────────────────────────────────────────┼─────────────┘  │
                                                   │                │
                                  HTTP /internal/run-task           │
                                                   │                │
┌──────────────────────────────────────────────────▼─────────────┐  │
│  StrategyExec 独立服务 (FastAPI :8001)                          │  │
│  ─── 完全独立, 不依赖 EvTrade 任何代码 ───                       │  │
│                                                                  │
│  api/internal.py (4 endpoint)                                    │
│    POST /internal/run-task     ─┐                                │
│    POST /internal/stop-task     │                                │
│    GET  /internal/tasks/{id}/status                                │
│    POST /internal/tasks/{id}/progress                            │
│                                  │                                │
│  ┌───────────────────────────────┘                                │
│  │                                                                │
│  ▼                                                                │
│  engines/backtrader/ (Backtrader 引擎)                           │
│    ├── backtest/   回测 (Backtrader.cerebro.run)                  │
│    ├── live/       实盘 (Backtrader + 行情 WS)                    │
│    └── adapter.py  bt.Strategy → publish_signal 适配层            │
│                                                                  │
│  signal_publisher.py ──► RabbitMQ strategy.exchange             │
│    routing_key = stock_code                                       │
│    payload = {task_id, signal_type: BUY/SELL, stock_code,        │
│               price, volume, indicators, ts}                      │
│                                                                  │
│  data_access.py ──► MySQL (共享 EVTRADE_DB_URL)                  │
│    读 strategy_script.code / params_schema                        │
│    写 strategy_task.progress / status / live_signals             │
│    写 strategy_script_audit                                       │
│                                                                  │
│  hq_ws_client.py ──► ws://hqserver:8765/quota.broadcast          │
│    (行情直连, 不走 EvTrade 后端转发)                              │
└──────────────────────────────────────────────────────────────────┘
```

### 1.3 物理部署

```
┌─────────────────────────────────────────────────────────────────┐
│  同一台 Linux / macOS 开发机 / 服务器                              │
│                                                                  │
│  EvTrade (FastAPI :8000)                                          │
│  └─ python -m uvicorn server.main:app --port 8000               │
│                                                                  │
│  StrategyExec (FastAPI :8001)                                    │
│  └─ python -m strategy_exec.main --port 8001                    │
│                                                                  │
│  hqserver (:8765, 独立 Python 进程)                              │
│  └─ python -m hq.hqserver                                         │
│                                                                  │
│  RabbitMQ (amqp://192.168.10.2:5672, 复用现有)                  │
│  └─ msgpacket.exchange (broker RPC, 已有)                       │
│  └─ quota.exchange (行情 FANOUT, 已有)                           │
│  └─ quota.broadcast.exchange (行情 topic, 已有)                 │
│  └─ strategy.exchange (新增, topic, durable=True)               │
│       └─ queue: EvTrade.StrategySignal (由 EvTrade 订阅)        │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 数据流（Data Flow）

### 2.1 用户新建任务（不跑）

```
ScriptTask.vue
  │
  │ POST /api/script-strategy/tasks  {script_id, stock_code, params, ...}
  ▼
EvTrade /api/script-strategy/tasks (POST)
  │
  │ 1. 权限校验 (current_user.id == user_id || admin)
  │ 2. INSERT strategy_task (status='created')
  │ 3. RETURN task_id
  ▼
ScriptTask.vue  ←  {id, status:'created', ...}
```

**完全不变** — 任务创建仍在 EvTrade。

### 2.2 用户启动任务（run）

```
ScriptTask.vue
  │
  │ POST /api/script-strategy/tasks/{task_id}/run  {mode:'backtest', ...}
  ▼
EvTrade /api/script-strategy/tasks/{id}/run (POST) — 转发 endpoint
  │
  │ 1. 权限校验 (current_user.id == task.user_id || admin)
  │ 2. 校验 task 状态 != running
  │ 3. UPDATE strategy_task SET status='queued', mode=:mode, started_at=NOW
  │ 4. HTTP POST strategy_exec:8001/internal/run-task
  │      Header: X-Internal-Token (env STRATEGY_EXEC_API_TOKEN)
  │      Body: {task_id, user_id, script_id, stock_code, params, mode,
  │             backtest_start_date, backtest_end_date, period, fields}
  │ 5. strategy_exec 立即返回 202 Accepted
  │ 6. EvTrade 立即返回 task 详情
  ▼
ScriptTask.vue  ←  {id, status:'queued', ...}

[后台] strategy_exec 异步处理:
  │
  │ 7. 从 DB 读 strategy_script.code (按 user_id + script_id 复合 PK)
  │ 8. 动态加载用户 Python (sandbox) — 用户脚本继承 bt.Strategy
  │ 9. Backtrader cerebro.run() — 回测同步跑完 / 实盘启动 asyncio loop
  │ 10. 写 progress / audit / live_signals 到 DB
  │ 11. 调 signal_publisher.publish_signal() → RabbitMQ
```

### 2.3 信号传递（关键路径）

```
StrategyExec 内用户脚本:
  class MyStrategy(bt.Strategy):
      def next(self):
          if self.data.close[0] > self.sma[0]:
              self.buy_signal(price=self.data.close[0], volume=100)
              # adapter.py 注入: 不是 self.buy() (Backtrader 本地),
              # 而是 self.buy_signal() (项目自定义, publish_signal)
                  │
                  ▼
              adapter.py 收到 buy_signal 调用
                  │
                  ├─► self.signals.record(type='BUY', ...)  # 写 strategy_script_audit
                  │
                  └─► signal_publisher.publish_signal(
                        task_id=self.task_id,
                        signal_type='BUY',
                        stock_code=self.data._name,    # Backtrader data feed name
                        price=self.data.close[0],
                        volume=100,
                        indicators={'sma': self.sma[0]},
                        ts=now()
                      )
                        │
                        ▼
                      RabbitMQ publish:
                        exchange='strategy.exchange'
                        routing_key=stock_code
                        body=JSON payload
                        confirm_timeout=5s
```

### 2.4 EvTrade 收信号 + 下单

```
RabbitMQ broker
  │
  │ routing_key=stock_code  →  queue=EvTrade.StrategySignal
  ▼
EvTrade server/services/strategy/signal_consumer.py
  │
  │ 1. aio_pika async consume queue EvTrade.StrategySignal
  │ 2. 反序列化 payload
  │ 3. 根据 signal_type 调自家 endpoint:
  │      BUY  → POST /api/orders/place  {stock_code, side:'23', price, volume}
  │      SELL → POST /api/orders/place  {stock_code, side:'24', price, volume}
  │ 4. 把下单单号 (order_no) 通过 progress 写回 strategy_task.live_signals
  │ 5. ACK RabbitMQ message
  ▼
[回到 EvTrade 主流程]
  /api/orders/place
    │
    ├─► INSERT orders (status=48) → 本地 INSERT
    ├─► 调 ord_stk RPC (msgpacket) → 柜台
    └─► broker ord_cfm push → push_handlers 写 orders.status
```

### 2.5 任务进度（推前端）

```
StrategyExec 引擎
  │
  │ 每 N 根 bar / 每 N tick 调一次:
  │   db.update('strategy_task', id=task_id,
  │             progress={phase, current, total, bar_idx, ...})
  ▼
DB strategy_task.progress 字段
  │
  │ (EvTrade ws_manager 没直读 DB, 需 signal_consumer 或 polling 触发)
  ▼
📌 方案 1: EvTrade signal_consumer 收到 broker ord_cfm 后,
            查 DB strategy_task.progress → ws_manager.broadcast('task_progress_update')
📌 方案 2: strategy_exec 每 1s 主动推 ws://evtrade:8000/_internal/task-progress?task_id=...
            EvTrade 端点收 → ws_manager.broadcast

[采用方案 1, 简单 — 不需新 endpoint, 复用现有 ws_manager]
```

### 2.6 用户停止任务

```
ScriptTask.vue
  │
  │ POST /api/script-strategy/tasks/{id}/stop
  ▼
EvTrade /api/script-strategy/tasks/{id}/stop (POST) — 转发 endpoint
  │
  │ 1. 权限校验
  │ 2. UPDATE strategy_task SET status='stopping'
  │ 3. HTTP POST strategy_exec:8001/internal/stop-task {task_id}
  │ 4. strategy_exec 找 LiveRunner._tasks[task_id], 调 cerebro.runstop() / stop()
  │ 5. strategy_exec UPDATE strategy_task SET status='stopped'
  │ 6. EvTrade 立即返 ok
```

## 3. RabbitMQ 拓扑

### 3.1 新增 exchange

| 配置 | 值 |
|---|---|
| exchange | `strategy.exchange` |
| type | `topic` |
| durable | `True` |
| auto_delete | `False` |

### 3.2 新增 queue

| 配置 | 值 |
|---|---|
| queue | `EvTrade.StrategySignal` |
| durable | `True` |
| bindings | `strategy.exchange` with `routing_key=stock_code` |
| consumer | EvTrade `signal_consumer.py`（single instance, 不并发消费）|

### 3.3 Signal Payload Schema

```json
{
  "task_id": 123,
  "user_id": 6,
  "script_id": "ma5_e2e",
  "signal_type": "BUY",       // "BUY" | "SELL" | "INFO"
  "stock_code": "600519.SH",
  "price": 1680.5,
  "volume": 100,
  "price_type": "limit",      // "limit" | "market"
  "indicators": {             // 用户脚本传, 透传给 audit
    "ma5": 1670.0,
    "ma20": 1650.0,
    "rsi": 65.4
  },
  "ts": "2026-08-09T10:30:15.123456",
  "trace_id": "uuid-v4",      // 幂等/追踪用
  "msg": "5日上穿20日, 量100"  // 用户脚本可填备注
}
```

### 3.4 Publisher 配置

- **Publisher Confirms** (`confirm_timeout=5s`) — 失败重试 3 次
- **持久化消息** (`delivery_mode=2`)
- **失败兜底**: RabbitMQ 推送失败 → 写 `strategy_task.error_msg` + `status='failed'`，前端可看

### 3.5 Consumer 配置

- **手动 ACK**（处理成功才 ACK）— 防止 signal_consumer 崩溃丢信号
- **prefetch_count=10** — 防止单 consumer 堆积
- **幂等**: 通过 payload `trace_id` 去重（EvTrade 端 `_processed_signal_ids` set，TTL 24h）

## 4. API 契约

### 4.1 EvTrade → strategy_exec HTTP endpoints（新增）

#### POST `/internal/run-task`

```http
POST strategy_exec:8001/internal/run-task
Content-Type: application/json
X-Internal-Token: <env STRATEGY_EXEC_API_TOKEN>

Request:
{
  "task_id": 123,
  "user_id": 6,
  "script_id": "ma5_e2e",
  "stock_code": "600519.SH",
  "mode": "backtest",
  "params": {"fast": 5, "slow": 20},
  "backtest_start_date": "20260101",
  "backtest_end_date": "20260630",
  "period": "1d",
  "fields": "open,close,high,low,volume"
}

Response 202 Accepted:
{
  "task_id": 123,
  "status": "accepted",
  "msg": "任务已提交, 后台异步执行"
}

Response 4xx:
- 400: 参数缺失
- 401: token 错误
- 404: task_id 不存在
- 409: 任务已在 running
- 503: strategy_exec 服务不可用
```

#### POST `/internal/stop-task`

```http
POST strategy_exec:8001/internal/stop-task
X-Internal-Token: <env>

Request:
{ "task_id": 123 }

Response 200:
{ "ok": true, "task_id": 123 }
```

#### GET `/internal/tasks/{task_id}/status`

```http
GET strategy_exec:8001/internal/tasks/123/status
X-Internal-Token: <env>

Response 200:
{
  "task_id": 123,
  "status": "running",   // created | running | stopped | failed | completed
  "mode": "backtest",
  "started_at": "...",
  "finished_at": null,
  "pnl": 0.0,
  "trades_count": 0,
  "progress": {"phase": "backtest_bar", "current": 500, "total": 10000},
  "live_signals_count": 0
}
```

#### POST `/internal/tasks/{task_id}/progress`

> **方案 2 触发路径** —— strategy_exec 主动回调 EvTrade（不需要则可省略）

```http
POST evtrade:8000/api/internal/strategy-exec/progress
X-Internal-Token: <env STRATEGY_EXEC_API_TOKEN>

Request:
{ "task_id": 123, "progress": {"phase": "bar", "current": 500, "total": 10000} }

Response 200: { "ok": true }
```

### 4.2 EvTrade signal_consumer（新增内部模块）

```python
# server/services/strategy/signal_consumer.py
class SignalConsumer:
    """订阅 RabbitMQ strategy.exchange/EvTrade.StrategySignal
    收到 signal → POST /api/orders/place"""
    
    async def start(self): ...
    async def stop(self): ...
    async def _handle_signal(self, payload: dict): ...
```

启动: 在 `server/main.py` 启动时 `asyncio.ensure_future(signal_consumer.start())`，与 ws_manager 初始化一起。

## 5. 数据模型变更

### 5.1 新增字段

```yaml
# server/schema.yml 增量

strategy_task:
  # ... 现有 23 字段
  execution_service:
    type: String(16)
    nullable: false
    default: 'evtrade'   # 'evtrade' = 原服务跑, 'strategy_exec' = 新服务跑
  execution_pid:
    type: Integer
    nullable: true
    default: null        # strategy_exec 实例的进程 pid, 用于排查
  version:
    type: Integer
    nullable: false
    default: 0           # 乐观锁, UPDATE 时 WHERE version=:v
```

### 5.2 迁移脚本

`server/migrations/2026-08-09-strategy-task-exec-fields.py`

```python
def migrate(engine):
    """幂等添加 3 字段"""
    with engine.begin() as conn:
        if not column_exists('strategy_task', 'execution_service'):
            conn.execute(text("""
                ALTER TABLE strategy_task
                ADD COLUMN execution_service VARCHAR(16) NOT NULL DEFAULT 'evtrade'
            """))
        if not column_exists('strategy_task', 'execution_pid'):
            conn.execute(text("""
                ALTER TABLE strategy_task
                ADD COLUMN execution_pid INT NULL DEFAULT NULL
            """))
        if not column_exists('strategy_task', 'version'):
            conn.execute(text("""
                ALTER TABLE strategy_task
                ADD COLUMN version INT NOT NULL DEFAULT 0
            """))
```

### 5.3 写竞争解决

```python
# strategy_exec 写 progress
UPDATE strategy_task
SET progress=:p, version=version+1
WHERE id=:tid AND version=:v

# EvTrade signal_consumer 写 status
UPDATE strategy_task
SET status=:s, version=version+1
WHERE id=:tid AND version=:v

# 冲突: WHERE version=:v 不匹配 → 重试 (max 3 次)
```

## 6. 用户脚本接口迁移

### 6.1 旧接口（v90）— 弃用

```python
# server/strategy/runtime/sandbox.py 注入的接口
def on_bar(ctx, bar):
    if bar['close'] > ctx.lib.MA(ctx.bars, 5):
        ctx.lib.doorder('600519.SH', 'BUY', bar['close'], 100)
```

### 6.2 新接口（Backtrader）— 推荐

```python
# strategy_exec/templates/default_bt_strategy.py
import backtrader as bt

class MyStrategy(bt.Strategy):
    params = (('fast', 5), ('slow', 20), ('qty', 100))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)

    def next(self):
        if not self.position and self.data.close[0] > self.sma_slow[0]:
            # project signal (不走 Backtrader 本地 broker)
            self.buy_signal(
                price=self.data.close[0],
                volume=self.p.qty,
                indicators={'sma_fast': self.sma_fast[0], 'sma_slow': self.sma_slow[0]},
                msg=f'金叉, ma5={self.sma_fast[0]:.2f}'
            )
        elif self.position and self.data.close[0] < self.sma_slow[0]:
            self.sell_signal(
                price=self.data.close[0],
                volume=self.position.size,
                indicators={'sma_fast': self.sma_fast[0]},
                msg=f'死叉'
            )

    def notify_signal_published(self, signal_id, ok):
        """可选回调: signal 推送给 RabbitMQ 成功/失败的回调"""
        if not ok:
            self.log.warning(f'signal {signal_id} 推送失败')
```

### 6.3 适配层（adapter.py）

```python
# strategy_exec/engines/backtrader/adapter.py
import backtrader as bt

class ProjectStrategy(bt.Strategy):
    """项目基类 — 提供 buy_signal / sell_signal 等项目专属方法"""
    
    def buy_signal(self, price, volume, **kw):
        """Backtrader 标准 self.buy() 改 self.buy_signal()"""
        from strategy_exec.signal_publisher import publish_signal
        from strategy_exec.signal_types import Signal, SignalType
        publish_signal(Signal(
            task_id=self._task_id,
            user_id=self._user_id,
            script_id=self._script_id,
            signal_type=SignalType.BUY,
            stock_code=self.data._name,
            price=price,
            volume=volume,
            indicators=kw.get('indicators', {}),
            msg=kw.get('msg', ''),
        ))

    def sell_signal(self, price, volume, **kw):
        # 对称实现
        ...
```

### 6.4 迁移助手

`strategy_exec/templates/migrate_from_v90.py` 提供：
- `v90_on_bar_to_next()` — 用户脚本转换助手
- 文档: `docs/strategy-migration-v90-to-bt.md` — v90 → Backtrader 迁移指南

## 7. 删除与迁移

### 7.1 删除的代码（Phase 4）

```
server/strategy/
├── __init__.py          # 简化 (移除 live / backtest re-export)
├── service.py           # ❌ 删 (999 行)
├── lib/
│   ├── __init__.py      # ⚠️ 简化 (移除 trading.py 中的 _LiveTradingFacade / PlaceOrderFacade)
│   ├── indicators.py    # ✅ 保留 (Backtrader 内置, 但可作为工具保留)
│   └── trading.py       # ❌ 删 (doorder/docancel 改在 strategy_exec)
├── runtime/
│   ├── backtest.py      # ❌ 删
│   ├── live.py          # ❌ 删
│   ├── grid.py          # ❌ 删
│   ├── sandbox.py       # ❌ 删
│   ├── fast_data.py     # ❌ 删
│   ├── his_hq.py        # ❌ 删 (broker fetch 改在 strategy_exec)
│   └── risk.py          # ❌ 删 (RiskChecker 继续在 server/services/risk.py)
├── tests/               # ⚠️ 全删 (test 文件针对旧引擎)
└── templates/
    └── default_script.py  # ❌ 删 (新 default 在 strategy_exec)

server/services/strategy/
└── quote_consumer.py    # ✅ 保留 (网格策略, 不在本 change 范围)
└── engine.py            # ✅ 保留 (网格策略)
```

### 7.2 修改的代码

```
server/api/script_strategy/endpoints.py
  - run_task endpoint → 转发到 strategy_exec
  - stop_task endpoint → 转发到 strategy_exec
  - 其他 CRUD endpoint 不变 (ScriptTask.vue 仍调这里)

server/main.py
  - 加 signal_consumer.start() (on_event('startup'))
  - 移除 strategy_api 引用 (网格策略保持, 见 server/api/strategy/)

server/api/strategy/  # 网格策略, 不在本 change 范围
```

### 7.3 新增的代码

```
strategy_exec/
├── pyproject.toml           # 独立依赖 (fastapi + backtrader + sqlalchemy + aio-pika + pika)
├── Dockerfile               # 多阶段构建
├── .env.example
├── README.md
├── strategy_exec/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry
│   ├── config.py            # Pydantic Settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── internal.py      # 4 endpoints
│   │   └── health.py        # /health
│   ├── engines/
│   │   ├── __init__.py
│   │   └── backtrader/
│   │       ├── __init__.py
│   │       ├── adapter.py       # bt.Strategy 基类 + buy_signal/sell_signal
│   │       ├── backtest.py      # 回测封装
│   │       └── live.py          # 实盘封装 (Backtrader + hqserver WS)
│   ├── data_access/
│   │   ├── __init__.py
│   │   ├── db.py               # SQLAlchemy session
│   │   ├── strategy_script.py  # 读 script code
│   │   ├── strategy_task.py    # 读/写 task
│   │   └── strategy_audit.py   # 写 audit
│   ├── signal/
│   │   ├── __init__.py
│   │   ├── types.py            # Signal / SignalType dataclass
│   │   └── publisher.py        # RabbitMQ publish
│   ├── market_data/
│   │   ├── __init__.py
│   │   ├── hq_ws_client.py     # 行情 WS (直连 hqserver)
│   │   └── hq_history.py       # 历史 K 线 (broker his_hq, 走 RabbitMQ)
│   ├── sandbox/
│   │   ├── __init__.py
│   │   └── loader.py           # 动态加载用户 Python (类似 v90 sandbox)
│   ├── risk/
│   │   └── __init__.py         # 占位 (无风控)
│   ├── templates/
│   │   └── default_bt_strategy.py  # 默认 Backtrader 模板
│   └── utils/
│       ├── __init__.py
│       └── logging.py
├── scripts/
│   └── evctl_strategy_exec.py  # 启动器 (仿 evctl.py)
└── tests/
    ├── test_adapter.py
    ├── test_backtest.py
    ├── test_publisher.py
    └── test_api.py
```

### 7.4 EvTrade 端新增

```
server/services/strategy/
└── signal_consumer.py    # 订阅 EvTrade.StrategySignal → POST /api/orders/place

server/api/internal/
├── __init__.py
└── strategy_exec_callback.py  # /api/internal/strategy-exec/progress (策略 4.1 POST progress)
```

## 8. 配置 / 环境变量

### 8.1 strategy_exec 独立 .env

```ini
# strategy_exec/.env
EVTRADE_DB_URL=mysql+pymysql://...                # 复用 (同库)
EVTRADE_RABBITMQ_URL=amqp://192.168.10.2:5672/   # 复用
EVTRADE_STRATEGY_EXCHANGE_NAME=strategy.exchange
EVTRADE_STRATEGY_SIGNAL_QUEUE=EvTrade.StrategySignal
HQ_WS_URL=ws://127.0.0.1:8765/quota.broadcast    # 行情直连
STRATEGY_EXEC_API_TOKEN=<shared-secret>            # EvTrade 调 strategy_exec 时校验
STRATEGY_EXEC_PORT=8001
LOG_LEVEL=INFO
```

### 8.2 EvTrade .env 新增

```ini
# server/.env 增量
STRATEGY_EXEC_API_URL=http://127.0.0.1:8001
STRATEGY_EXEC_API_TOKEN=<shared-secret>      # 与 strategy_exec 一致
EVTRADE_STRATEGY_EXCHANGE_NAME=strategy.exchange
EVTRADE_STRATEGY_SIGNAL_QUEUE=EvTrade.StrategySignal
```

## 9. 测试策略

### 9.1 strategy_exec 单元测试

```python
# strategy_exec/tests/test_adapter.py
def test_buy_signal_publishes_to_rabbit():
    strategy = ProjectStrategy()
    with mock_signal_publisher() as publisher:
        strategy.buy_signal(price=100, volume=100)
        publisher.publish.assert_called_once()
        call_args = publisher.publish.call_args[0][0]
        assert call_args.signal_type == SignalType.BUY
        assert call_args.price == 100
        assert call_args.volume == 100

# strategy_exec/tests/test_backtest.py
def test_backtest_simple_ma_cross():
    """金叉 → BUY signal, 死叉 → SELL signal"""
    bars = [Bar(...), Bar(...), ...]  # 30 根日线
    signals = run_backtest(code=DEFAULT_BT_STRATEGY, bars=bars, ...)
    assert len([s for s in signals if s.signal_type == BUY]) == 1
    assert len([s for s in signals if s.signal_type == SELL]) == 0

# strategy_exec/tests/test_api.py
def test_run_task_404():
    response = client.post('/internal/run-task',
                           json={'task_id': 99999, ...},
                           headers={'X-Internal-Token': TEST_TOKEN})
    assert response.status_code == 404
```

### 9.2 EvTrade 端集成测试

```python
# server/tests/script_strategy/test_forwarding.py
def test_run_task_forwards_to_strategy_exec(httpx_mock):
    httpx_mock.add_response(
        url='http://strategy_exec:8001/internal/run-task',
        method='POST',
        json={'task_id': 123, 'status': 'accepted'},
        status_code=202,
    )
    response = client.post('/api/script-strategy/tasks/123/run',
                           json={'mode': 'backtest', ...},
                           headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 202
    httpx_mock.get_request().assert_called_once()

def test_signal_consumer_invokes_place_order():
    """Mock RabbitMQ 收到 BUY signal → 验证调 /api/orders/place"""
    with mock_consumer() as consumer:
        consumer.inject(signal_buy_payload)
        # 验证
        assert mock_place_order.called
        call_kwargs = mock_place_order.call_args.kwargs
        assert call_kwargs['stock_code'] == '600519.SH'
        assert call_kwargs['volume'] == 100
```

## 10. 迁移路径

### Phase 1: 骨架 (1 天)

- 建 `strategy_exec/` 目录 + pyproject.toml + .env.example
- 写骨架代码 (FastAPI app + 4 endpoint 占位)
- 写启动脚本 `evctl_strategy_exec.py`
- 验证: `python -m strategy_exec.main` 能跑, 4 endpoint 返回 mock

### Phase 2: Backtrader 集成 (1.5 天)

- `pip install backtrader` (新增依赖)
- `strategy_exec/engines/backtrader/adapter.py` (ProjectStrategy 基类)
- `strategy_exec/engines/backtrader/backtest.py` (回测封装)
- `strategy_exec/engines/backtrader/live.py` (实盘封装 + 行情 WS)
- `strategy_exec/signal/publisher.py` (RabbitMQ publish)
- `strategy_exec/market_data/hq_ws_client.py` (行情订阅)
- `strategy_exec/market_data/hq_history.py` (历史 K 线, 走 broker his_hq)
- 测试: 单元测试通过

### Phase 3: EvTrade 集成 (1 天)

- `server/services/strategy/signal_consumer.py` (新增)
- `server/api/script_strategy/endpoints.py` run_task / stop_task 改转发
- `server/main.py` startup 启动 signal_consumer
- `server/api/internal/strategy_exec_callback.py` (progress 回调, 可选)
- 测试: 集成测试通过

### Phase 4: 清理 (1 天)

- 删 `server/strategy/service.py` + `runtime/*` + `lib/trading.py` + `templates/default_script.py`
- 迁移 `server/migrations/2026-08-09-strategy-task-exec-fields.py` (3 字段)
- 跑 `python scripts/sync_schema.py apply`
- 测试: 所有旧测试删除, 新 smoke 测试通过

### Phase 5: 文档 + 归档 (1 天)

- 写 `strategy_exec/README.md` (启动 / 配置 / 调试)
- 写 `docs/strategy-migration-v90-to-bt.md` (用户脚本迁移指南)
- 更新 `openspec/specs/strategy-exec/spec.md` (新能力 spec)
- 更新 `openspec/specs/strategy/spec.md` (删 REQ-STRAT-014~017, 标"已迁")
- 更新 `openspec/specs/data-model/spec.md` (3 新字段说明)
- 更新 `openspec/specs/configuration/spec.md` (4 新 env)
- commit + 归档 change

## 11. 已知限制 / Future Work

| 限制 | 影响 | 后续 change |
|---|---|---|
| 用户脚本需重写为 Backtrader | 现有用户脚本（~100）需手动迁移 | 后续: 自动迁移脚本 + 文档 |
| 网格策略未独立化 | 仍走 `server/services/strategy/` | 后续 change |
| 策略回测报告可视化简陋 | Backtrader 默认输出仅文本 | 后续: 接 plotly.js / 自研报告 |
| strategy_exec 单实例 | 不可水平扩展 | 后续: HA 部署 |
| Backtrader 性能 | 回测 1 万根 bar ~2s, 1 百万根 ~30s | 后续: 增量回测 / 分布式回测 |