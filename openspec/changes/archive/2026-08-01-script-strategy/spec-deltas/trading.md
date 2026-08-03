# spec-delta: trading

## 新增模块: server/strategy/

### lib/indicators.py — 纯函数指标

```python
def MA(bars: list[dict], period: int, field: str = 'close') -> float | None
def EMA(bars: list[dict], period: int, field: str = 'close') -> float | None
def RSI(bars: list[dict], period: int = 14, field: str = 'close') -> float | None
def MACD(bars: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float] | None
def BOLL(bars: list[dict], period: int = 20, stddev: float = 2.0, field: str = 'close') -> tuple[float, float, float] | None
def KDJ(bars: list[dict], n: int = 9, m1: int = 3, m2: int = 3) -> tuple[float, float, float] | None
def ATR(bars: list[dict], period: int = 14) -> float | None
def BARSLAST(bars: list[dict], cond) -> int  # 距上次 cond() 为 True 的 bar 数
def REF(bars: list[dict], n: int) -> float | None  # N bar 前的收盘价
def CROSS(a: float, b: float) -> bool  # a 上穿 b(今 a>b, 昨 a<=b)
```

所有指标返回 `None` 当 bars 长度不足。

### lib/trading.py — 下单 / 撤单 wrapper

```python
def doorder(stock_code: str, side: str, price: float, volume: int, ctx: dict = None) -> str:
    """返回 order_no;回测模式下不实际下单,仅记录到 ctx.audit_log"""

def docancel(order_no: str, trd_date: str, ctx: dict = None) -> bool:
    """回测模式下 noop"""

def get_position(stock_code: str, ctx: dict = None) -> int:
    """持仓量(回测模式维护模拟持仓)"""
```

回测 / 实盘共用同一份脚本。ctx.mode 区分('backtest' / 'live')。

### runtime/sandbox.py — 安全沙箱

```python
def load_script(code: str, params: dict) -> dict:
    """
    编译 + 加载用户脚本为模块对象。
    globals 注入:
      - lib: 已暴露 lib facade (MA/EMA/doorder/docancel 等)
      - params: 用户传入的参数 dict (如 {'fast': 5, 'slow': 20})
      - math / datetime 等白名单标准库
      - 不允许 os / subprocess / socket / requests / importlib
    返回: dict 含 on_init / on_bar / on_tick / on_finish 4 个回调(用户实现哪些就调哪些)
    """
```

### runtime/backtest.py

```python
class BacktestEngine:
    def __init__(self, script_code, params, bars, initial_cash=100000.0):
        ...

    async def run(self) -> BacktestResult:
        """
        bars: 从 hqserver.his_hq 拉 [{stime, open, high, low, close, volume}, ...]
        流程:
          1. load_script
          2. ctx.bars = [] 累积
          3. on_init(ctx)
          4. 逐 bar:
              - ctx.bars.append(bar)
              - on_bar(ctx, bar)
              - 用户脚本可能调 doorder/doorder(回测模式只审计不真下单)
          5. on_finish(ctx)
          6. 计算 PnL / win_rate / sharpe / equity_curve
          7. 返回 BacktestResult
        """
```

### runtime/grid.py — 参数笛卡尔积

```python
def expand_params(schema: list[dict]) -> list[dict]:
    """
    schema = [{"key": "fast", "type": "int", "min": 3, "max": 10, "step": 1},
              {"key": "slow", "type": "int", "min": 15, "max": 30, "step": 5}]
    → [{"fast": 3, "slow": 15}, {"fast": 3, "slow": 20}, ..., {"fast": 10, "slow": 30}]
    """
```

### runtime/live.py

```python
class LiveRunner:
    def __init__(self, task_id, script_code, params, stock_code):
        ...

    async def start(self):
        """
        1. 加载 hqserver ws 订阅 stock_code 的 tick
        2. 维护 ctx.bars(累积 1m K 线)
        3. 每 bar 触发 on_bar
        4. 每 tick 触发 on_tick
        5. 用户脚本调 doorder → 走 server.api.orders.ord_stk
        """
```

## API 端点(server/api/script_strategy/endpoints.py)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/script-strategy/scripts` | 列出脚本 |
| GET | `/api/script-strategy/scripts/{id}` | 详情 |
| POST | `/api/script-strategy/scripts` | 新建 |
| PUT | `/api/script-strategy/scripts/{id}` | 更新 |
| DELETE | `/api/script-strategy/scripts/{id}` | 删除 |
| GET | `/api/script-strategy/tasks` | 列出任务 |
| GET | `/api/script-strategy/tasks/{id}` | 详情 |
| POST | `/api/script-strategy/tasks` | 新建任务(回测/实盘),返回 task_id |
| POST | `/api/script-strategy/tasks/{id}/stop` | 停止任务 |
| DELETE | `/api/script-strategy/tasks/{id}` | 删除任务 |
| GET | `/api/script-strategy/tasks/{id}/logs` | 运行日志(回测完整 / 实盘最近 N 条) |

## 安全

- 脚本沙箱:白名单 globals + 禁 __import__ + 禁 file I/O + 禁网络
- 实盘任务启动需 user role >= trader(已有 _AUTH 依赖守卫,无需额外)
- 单用户脚本长度限制 50KB(防止内存炸弹)

## 与现有模块的关系

| 现有 | 关系 |
|---|---|
| `server/services/strategy/` (规则引擎) | 完全独立,不动 |
| `server.api.orders.ord_stk` | live 模式 doorder 调它 |
| `server.rpc.client.cancel_order` | live 模式 docancel 调它 |
| `iquant/quota_his_test.py` | 参考 demo 思路,**不**复用其 MQ 通道,改用 hqserver `his_hq` API |