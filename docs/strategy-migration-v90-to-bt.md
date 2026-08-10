# 用户脚本迁移指南：v90 脚本引擎 → Backtrader（strategy_exec）

> 适用 change：`2026-08-09-strategy-exec-service`（v120）
> 目标：把旧 v90 脚本策略（`on_bar` / `on_tick` / `ctx.lib.doorder`）迁移到新的 Backtrader 接口（`ProjectStrategy.next()` + `self.buy_signal()`）。
> 引擎文档：`openspec/specs/strategy-exec/spec.md`（REQ-SE-003 引擎 / REQ-SE-005 用户脚本接口）。

## 为什么是 BREAKING

v120 起，策略运行引擎从 EvTrade 主进程 `server/strategy/runtime/`（自研简易引擎）迁到独立服务 `strategy_exec/`（基于 Backtrader，业界标准框架）。用户脚本的**接口完全更换**：

| 维度 | v90（旧） | v120 Backtrader（新） |
|---|---|---|
| 脚本形态 | 模块级回调函数 | 继承 `ProjectStrategy(bt.Strategy)` 的类 |
| 每根 K 线 | `on_bar(ctx, bar)` | `def next(self)` |
| 每个 tick | `on_tick(ctx, tick)` | `def next(self)`（1m K 线累积后触发）|
| 启动钩子 | `on_init(ctx)` | `def __init__(self)`（定义指标）|
| 结束钩子 | `on_finish(ctx)` | `def stop(self)`（可选）|
| 下单 | `doorder(code, 'BUY', price, qty)` | `self.buy_signal(price, volume)` |
| 平仓 | `doorder(code, 'SELL', price, qty)` | `self.sell_signal(price, volume)` |
| 撤单 | `docancel(order_no, trd_date)` | 不在用户脚本内（信号模型，撤单由 EvTrade 交易端处理）|
| 查持仓 | `get_position(code)` | `self.get_position()` |
| 指标 | `MA / EMA / RSI / MACD / BOLL / KDJ / ATR / BARSLAST / REF / CROSS` | `bt.indicators.SMA / EMA / RSI / MACD / BollingerBands / Stochastic / ...` + `bt.indicators.CrossOver` |
| 参数 | `ctx['params']['fast']` | `self.p.fast`（类 `params` 元组）|
| 状态 | `ctx['state'][...]` | 实例属性（如 `self.position` / 自定义 `self._flag`）|

**核心差异**：v90 是"上下文对象 + 全局函数"；Backtrader 是"策略类 + 实例方法"。信号不直接下单，而是 `buy_signal()/sell_signal()` 推 RabbitMQ，由 EvTrade `signal_consumer` 落 `/api/orders/place`。

## 接口速查（ProjectStrategy）

```python
import backtrader as bt
from strategy_exec.engines.backtrader.adapter import ProjectStrategy

class MyStrategy(ProjectStrategy):
    params = (("fast", 5), ("slow", 20), ("qty", 100))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)

    def next(self):
        price = self.data.close[0]
        if not self.position and self.data.close[0] > self.sma_slow[0]:
            self.buy_signal(price=price, volume=self.p.qty,
                            indicators={"ma5": self.sma_fast[0]}, msg="金叉")
        elif self.position:
            self.sell_signal(price=price, volume=self.position.size,
                             indicators={"ma5": self.sma_fast[0]}, msg="死叉")
```

可用方法：
- `self.buy_signal(price, volume, *, price_type='limit', indicators={}, msg='')` → 推送 BUY signal，成功返 trace_id
- `self.sell_signal(price, volume, *, price_type='limit', indicators={}, msg='')` → 推送 SELL signal
- `self.get_position()` → 本地持仓量（`self.position.size`）
- `self.get_cash()` → 本地现金
- `self.notify_signal_published(signal_id, ok)` → 可选推送结果回调

## 三个典型迁移例子

### 例 1：双均线交叉

**v90**：

```python
def on_bar(ctx, bar):
    fast, slow = ctx['params']['fast'], ctx['params']['slow']
    qty = ctx['params']['qty']
    ma_fast = MA(ctx['bars'], fast)
    ma_slow = MA(ctx['bars'], slow)
    prev_fast = MA(ctx['bars'][:-1], fast)
    prev_slow = MA(ctx['bars'][:-1], slow)
    pos = ctx['state'].get('position', 0)

    if prev_fast is None or prev_slow is None or ma_fast is None or ma_slow is None:
        return
    if prev_fast <= prev_slow and ma_fast > ma_slow and pos == 0:
        doorder(ctx['symbol'], 'BUY', bar['close'], qty)
        ctx['state']['position'] = 1
    elif prev_fast >= prev_slow and ma_fast < ma_slow and pos == 1:
        doorder(ctx['symbol'], 'SELL', bar['close'], qty)
        ctx['state']['position'] = 0
```

**v120 Backtrader**：

```python
class MAStrategy(ProjectStrategy):
    params = (("fast", 5), ("slow", 20), ("qty", 100))

    def __init__(self):
        self.crossover = bt.indicators.CrossOver(
            bt.indicators.SMA(period=self.p.fast),
            bt.indicators.SMA(period=self.p.slow),
        )

    def next(self):
        price = self.data.close[0]
        if self.crossover[0] > 0 and not self.position:
            self.buy_signal(price=price, volume=self.p.qty,
                            indicators={"ma_fast": self.crossover.lines[0][0],
                                        "ma_slow": self.crossover.lines[1][0]},
                            msg="金叉")
        elif self.crossover[0] < 0 and self.position:
            self.sell_signal(price=price, volume=self.position.size, msg="死叉")
```

> 要点：`bt.indicators.CrossOver` 直接返回 `>0`（金叉）/`<0`（死叉），不再手动比较前后两根均线；持仓由 Backtrader broker 管理（`self.position`），不用 `ctx['state']` 手记。

### 例 2：突破策略（N 日新高）

**v90**：

```python
def on_bar(ctx, bar):
    n, qty = ctx['params']['n'], ctx['params']['qty']
    highs = [b['high'] for b in ctx['bars']]
    if len(highs) < n + 1:
        return
    if bar['high'] >= max(highs[-n - 1:-1]) and not ctx['state'].get('pos'):
        doorder(ctx['symbol'], 'BUY', bar['close'], qty)
        ctx['state']['pos'] = 1
    elif bar['low'] <= min(b['low'] for b in ctx['bars'][-n - 1:-1]) and ctx['state'].get('pos'):
        doorder(ctx['symbol'], 'SELL', bar['close'], qty)
        ctx['state']['pos'] = 0
```

**v120 Backtrader**：

```python
class BreakoutStrategy(ProjectStrategy):
    params = (("n", 20), ("qty", 100))

    def __init__(self):
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.n)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.n)

    def next(self):
        if not self.position and self.data.high[0] >= self.highest[-1]:
            self.buy_signal(price=self.data.close[0], volume=self.p.qty, msg="突破 N 日新高")
        elif self.position and self.data.low[0] <= self.lowest[-1]:
            self.sell_signal(price=self.data.close[0], volume=self.position.size, msg="跌破 N 日新低")
```

> 要点：`bt.indicators.Highest/Lowest` 自动维护滚动窗口，`[-1]` 取上一根（不含当前），免去切片取 max/min。

### 例 3：多标的轮动（按均线排序选强）

**v90**（伪代码，逐标的 ctx 各自回调）：

```python
# v90 每标的独立运行, 跨标的排序需外部聚合
def on_bar(ctx, bar):
    ma = MA(ctx['bars'], ctx['params']['fast'])
    if ma is None:
        return
    # 只能处理当前 ctx['symbol'] 一个标的
    if bar['close'] > ma and not ctx['state'].get('pos'):
        doorder(ctx['symbol'], 'BUY', bar['close'], ctx['params']['qty'])
        ctx['state']['pos'] = 1
```

**v120 Backtrader**（同一策略类加多个 data feed，`self.data[i]` 索引各标的）：

```python
class RotationStrategy(ProjectStrategy):
    params = (("fast", 20), ("qty", 100))

    def __init__(self):
        self.ma = [bt.indicators.SMA(d, period=self.p.fast)
                   for d in self.datas]

    def next(self):
        # 每根 bar 对所有标的同时评估
        for i, d in enumerate(self.datas):
            if not self.getposition(d).size and d.close[0] > self.ma[i][0]:
                self.buy_signal(price=d.close[0], volume=self.p.qty, msg=f"标的{i} 多头")
            elif self.getposition(d).size and d.close[0] < self.ma[i][0]:
                self.sell_signal(price=d.close[0], volume=self.getposition(d).size, msg=f"标的{i} 空头")
```

> 要点：Backtrader 原生支持多数据源（`self.datas`），跨标的轮动在同一个 `next()` 里完成；逐标的持仓用 `self.getposition(data)` 查询。

## 迁移清单（逐条核对）

- [ ] 脚本从"模块级回调"改为"类"：`class XxxStrategy(ProjectStrategy)`，类名随意
- [ ] `on_init(ctx)` → `__init__` 里定义全部指标（`self.sma = bt.indicators.SMA(...)`）
- [ ] `on_bar(ctx, bar)` / `on_tick(ctx, tick)` → `next()`（回测逐 bar、实盘 1m K 线触发）
- [ ] `ctx['params']['x']` → `self.p.x`（把参数写进 `params = (("x", 默认值), ...)`）
- [ ] `MA/EMA/RSI/MACD/BOLL/KDJ` → `bt.indicators.SMA/EMA/RSI/MACD/BollingerBands/Stochastic`
- [ ] `CROSS(a, b)` → `bt.indicators.CrossOver(a, b)`（`[0]>0` 金叉 / `[0]<0` 死叉）
- [ ] `BARSLAST/REF` → Backtrader 数据切片 `self.data.close[-1]` / `self.data.close[-n]`（指标自动提前算好）
- [ ] `doorder(code,'BUY',...)` → `self.buy_signal(price, volume, ...)`
- [ ] `doorder(code,'SELL',...)` → `self.sell_signal(price, volume, ...)`（平仓用 `volume=self.position.size`）
- [ ] `get_position(code)` → `self.get_position()`（单标的）或 `self.getposition(data).size`（多标的）
- [ ] `ctx['state']` → 实例属性（`self._flag = ...`）或直接靠 `self.position` / 指标
- [ ] `on_finish(ctx)` → `def stop(self)`（可选，Backtrader 结束钩子）
- [ ] `ctx['symbol']` → `self.data._name`（数据源名 = stock_code，无需手取）
- [ ] 删除 `ctx['mode']` 判断（回测/实盘由 strategy_exec 引擎注入，`self._task_mode` 已置好）

## 常见问题

- **金叉死叉用 `CrossOver` 还是手动比较**？推荐 `bt.indicators.CrossOver`——Backtrader 自动处理边界与 warmup。
- **指标 warmup 期间 None？** Backtrader 用 `bt.indicators` 会自动从第 N 根 bar 才有值，`next()` 里用 `if len(self) < self.p.slow + 1: return` 跳过即可（或用 `self.sma[0]` 前判 `len(self) < self.p.slow`）。
- **信号没推出去？** 检查 `self.buy_signal()` 返回值：`None` 表示推送失败（RabbitMQ 不可达/重试耗尽），看 `strategy_task.error_msg`。
- **实盘 tick 频率**：实盘是 tick → 累积 1m K 线 → `next()`，不是逐 tick 调。需逐 tick 逻辑时用 `self.data` 最新价判断，但 signal 生成按 bar。
- **本地回测验证**：`cd strategy_exec && python -m strategy_exec.main` 后，用 `strategy_script` 表保存脚本，ScriptTask.vue 启动回测，看 `strategy_script_audit` 与 `strategy_task.backtest_result`。

## 相关文档

- 引擎能力：`openspec/specs/strategy-exec/spec.md` REQ-SE-003 / REQ-SE-005
- 默认模板：`strategy_exec/strategy_exec/templates/default_bt_strategy.py`
- 信号推送：REQ-SE-004（RabbitMQ `strategy.exchange`）
- 旧 v90 引擎已删除：commit `aa70dae`（`server/strategy/runtime/`）
