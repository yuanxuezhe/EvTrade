# Backtrader 引擎

## 对应代码路径

- `e:/EvTrade/strategy_exec/strategy_exec/engines/backtrader/adapter.py`（ProjectStrategy 基类）
- `e:/EvTrade/strategy_exec/strategy_exec/engines/backtrader/backtest.py`（回测引擎）
- `e:/EvTrade/strategy_exec/strategy_exec/engines/backtrader/live.py`（实盘引擎）
- `e:/EvTrade/strategy_exec/strategy_exec/engines/backtrader/sweep.py`（参数扫描引擎）

## 功能概述

`engines/backtrader/` 是策略执行核心：用户脚本继承 `ProjectStrategy`（bt.Strategy 子类），通过 `buy_signal()/sell_signal()` 推送信号；backtest.py 同步跑完整回测并落库；live.py 以 LiveRunner 常驻订阅行情 WS 逐 bar 驱动 `next()`；**worker.py 以 worker 池 FIFO 有界并发从 DB 队列领 task 跑回测 + 堵塞自愈**（change 2026-08-30-sweep-worker-queue，取代旧 sweep gather 一把梭）；sweep.py 保留参数展开纯函数（执行已弃用）。

## 文件清单

| 代码文件 | 作用 |
|----------|------|
| `adapter.py` | `ProjectStrategy` 基类：任务元数据注入、信号推送、持仓/现金查询 |
| `backtest.py` | `run_backtest()` 主流程 + `_wrap_strategy()` 类装饰 + `_update_task_results()` 乐观锁写结果（含代际守卫） |
| `live.py` | `_BarAggregator`（tick→1m K 线）、`LiveRunner`、`_LiveRunnerManager` 单例 |
| `worker.py` | 回测任务执行队列：`run_worker_pool()` 起 N worker FIFO 有界并发（claim→run→复位超时→下一）+ `_finalize_batch()` top1 回写 best_params（change 2026-08-30-sweep-worker-queue） |
| `sweep.py` | 参数展开纯函数（`_expand_values`/`iter_param_ranges`/`extract_metric_value` 等，worker 复用）；`run_sweep_batch()` 已 **DEPRECATED**（端点改走 worker 池，函数仅测试/回退参考） |

## 核心实现

### adapter.py — ProjectStrategy

用户脚本不直接继承 bt.Strategy，而是继承 `ProjectStrategy`，获得：

- `buy_signal(price, volume, *, price_type="limit", indicators=None, msg="") -> Optional[str]`：推送 BUY，成功返 trace_id。
- `sell_signal(...)`：同上 SELL。
- `notify_signal_published(signal_id, ok)`：可选回调（用户可 override）。
- `get_position() -> int` / `get_cash() -> float`：查 Backtrader broker 状态。

类属性 `_task_id/_user_id/_script_id/_task_mode/_parent_task_id/_strategy_name` 由引擎在 addstrategy 前通过 `_set_task_meta(task_id, user_id, script_id, mode, parent_task_id, strategy_name)` 注入（含母单归因两字段）。`_bar_time()` 返当前 bar 时间 `YYYYMMDDHHMMSS`。

`_publish()` 关键线程问题：回测跑在 `asyncio.to_thread` 中，Backtrader `next()` 是同步代码；publish 是 async → 用 `asyncio.run_coroutine_threadsafe(coro, publisher.loop)` 投递到 publisher connect 时绑定的主 loop，`future.result(timeout=10)` 同步等待；publisher 未连接时退回 `asyncio.run(coro)` best-effort。失败抛 `SignalPublishError` → 返 None。

### backtest.py — run_backtest 主流程

```python
def run_backtest(task_id, user_id, script_id, stock_code, params, bars,
                 backtest_start_date=None, backtest_end_date=None,
                 period="1d", strategy_id=None, update_strategy_best=False) -> Dict
```

1. `update_task_status(task_id, "running", execution_pid=os.getpid())`。
2. 加载脚本：`get_script(user_id, script_id)` 读 code + params_schema → `load_strategy_class(code, ProjectStrategy, params_schema=...)`（失败 → status=failed 并 raise）。
3. 构造 Cerebro：`cerebro.addstrategy(cls, **params)`；`_make_pandas_data_feed(bars)` 把 his_hq 返回的 dict 列表转 `bt.feeds.PandasData`（字符串 OHLCV `pd.to_numeric`，`stime`(%Y%m%d%H%M%S) 转 datetime index，缺 'open' 列报错）；`data._name = stock_code`；`setcash(100000.0)`；`setcommission(0.0)`（手续费 0，实盘由 EvTrade 算）。
4. 分析器：`TimeReturn`（timeframe=Days）+ `SharpeRatio`（timeframe=Days）。`_get_analyzer_value` 取 `sharperatio` 字段（0/None 归 None）。
5. `_wrap_strategy(...)` 装饰策略类后 `cerebro.run()`。
6. 结果：`pnl = broker.getvalue() - 100000`；每条 signal 写 `write_audit(...)`（strategy_script_audit 表）。
7. `backtest_result` dict 落库（契约对齐前端 ScriptTask.vue）：
   - 顶层：`pnl / pnl_pct / final_value / initial_cash / bars_count / sharpe / signal_log / total_bars / execution_log`
   - `best`：`{pnl, pnl_pct(小数), win_rate, trades_count, trades, signal_log}`（pnl_pct/win_rate 存小数，前端 ×100）。**不含 `progress_log`/`equity_curve`**（change 2026-08-30-drop-fullbar-progress：全量逐 bar 不再落库）
8. `_update_task_results(...)` 上下文管理器：直接 SQL 乐观锁（version 字段）写 `backtest_result/pnl/trades_count/backtest_metric_value`，冲突重试 3 次；随后 `update_task_status(task_id, "finished", finished_at=...)`（终态统一 `finished`）。
9. `update_strategy_best=True` 且成功 → `update_strategy_best_params(strategy_id, params)` 回写 `strategy.best_params`（扫描批次内为 False，由 sweep 统一写）。

`_metric_value_from_result`：提取展示指标（sharpe → total_return → pnl/initial_cash 回退），语义与 server `services/script_strategy/_convert.py` 的 `_extract_metric_value` 一致，规避 MySQL 1038 排序内存错误。

### _wrap_strategy — 类装饰器（回测核心技巧）

对用户策略类的 4 个方法打补丁：

- `patched_init`：原 init 后调 `_set_task_meta(task_id, user_id, script_id, mode="backtest")`。
- `patched_next`：每根 bar 后记录 `progress_log` 条目 `{bar_idx, stime, close, position, cash, equity}`（**run 内内存缓冲，不落地** — 仅供 `_build_signal_bar_entries` 取信号 bar 快照）；节流 ≥0.5s 上报 `update_task_progress(task_id, {phase:"running", bar_idx, total_bars})`（运行进度环数据源，保留）。
- `patched_buy/patched_sell`：先调原 `buy_signal/sell_signal`（推 RabbitMQ），拿到 trace_id 后**同时下 Backtrader 市价单**（下一 bar 成交）使 broker 持仓/现金/盈亏真实累积；维护长仓口径 `pos_tracker`（size/avg 均价），SELL 计算 `realized = (price - avg) * close_vol` 作为信号 pnl；collector 记录含 `state/pnl/trace_id/stime/mode="backtest"` 的完整信号 dict。

执行日志 `exec_log`：阶段时间轴（start/load_script/sandbox_ok/build_cerebro/running/writing_result/done，含 elapsed_ms）+ **仅触发信号的 bar**（`_build_signal_bar_entries(signals, progress_log)`：遍历 buy/sell_signal 命中，按 stime 查回 bar_idx/close/position/equity，msg=`signal_type vol=<v> (<策略 msg>)`）。不逐 bar 全量。**全量逐 bar（progress_log/equity_curve）不再落库**（change 2026-08-30-drop-fullbar-progress）；前端「进度」Tab 已删，权益曲线改用 execution_log 信号 bar 的 `{stime, equity}` 绘制（起点 `initial_cash`）。

### live.py — 实盘引擎

`_BarAggregator.on_tick(tick)`：按 `stime` 前 4 位（HHMM）分桶聚合 tick 为 1m K 线，分钟切换时返回上一根完整 bar。tick 格式：`{stime:'HHMMSS', lastPrice, open, high, low, volume}`。

`LiveRunner`（单 live 任务）：

- `_run()`：`load_strategy_class` 加载 → 临时 `bt.Cerebro`（无 data feed，setcash 100000，`cerebro.run()` 跑一步拿 strategy instance）→ `_set_task_meta(..., mode="live", parent_task_id, strategy_name)` → WS 主循环（指数退避重连：base=HQ_WS_RECONNECT_BASE_DELAY/1000 秒起，翻倍至 max）。
- `_connect_and_consume()`：`websockets.connect(hq_ws_url, ping_interval=..., ping_timeout=...)` → 发订阅 `{"type": "subscribe", "stock_codes": [stock_code]}` → 收 `{"type":"quote","data":{...}}`，过滤本标的 tick → `_on_tick`。
- `_on_tick`：聚合出完整 bar 后手动调 `self._strategy_instance.next()`（Backtrader next 是 sync，loop 内直接调）；next 异常 → status=failed 并停止。每 `LIVE_SIGNAL_FLUSH_INTERVAL=5s` 把 `_signal_buffer`（deque maxlen=500）flush 到 `append_live_signals` 并 `update_task_progress`。

`_LiveRunnerManager` 模块级单例 `_manager`：按 task_id 注册表。`start_live_runner(...)` 读脚本后创建 runner 并注册；`stop_live_runner(task_id)`、`is_running(task_id)`、`stop_all_live_runners()`（应用关闭用）。

### sweep.py — 参数扫描（strategy-batch-task-model）

约定：EvTrade 调用前已为批次预建好 strategy_task 行（strategy_id + batch_no + params 落库），strategy_exec 不自建 task / summary task。

常量：`SWEEP_SOFT_WARN=64`（超仅警告）、`SWEEP_HARD_LIMIT=512`（超直接 raise）、`ALLOWED_METRICS=("sharpe","total_return","calmar")`。

纯函数（单测友好）：

- `_expand_values(spec)`：按 `type` 展开 —— int/float 按 start/end/step 含端点（float 末位钳到 end 防漂移）；choice 取 values；string 取单值 value。
- `iter_param_ranges(param_ranges)`：展开后单值参数进 `fixed`（不参与笛卡尔积），多值进 `active`，`itertools.product` 产出组合；空参数整体跳过。
- `count_param_ranges` / `validate_grid_size` / `validate_metric` / `extract_metric_value`（sharpe 直取；total_return=pnl/initial_cash；calmar=total_return/|max_drawdown|，无 max_drawdown analyzer 时 None）。

`run_sweep_batch(strategy_id, batch_no, user_id, script_id, stock_code, param_ranges, metric, backtest_start_date, backtest_end_date, *, period="1d", concurrency=2) -> Dict`：

1. 校验 metric / grid。
2. `get_batch_tasks(strategy_id, batch_no)` 读批次内 task（不存在 → RuntimeError；数量与展开数不符 → warning 后按 DB 实际跑）。
3. `fetch_his_bars` 拉一次 K 线，全组合共享。
4. `asyncio.Semaphore(concurrency)` + `asyncio.gather` 并发 `_run_one`（内部 `asyncio.to_thread(run_backtest, ..., update_strategy_best=False)`）；单组合失败 → 该 task status=failed，其余继续（容错）。
5. finished 组合按 metric 降序取 top1 → `update_strategy_best_params(strategy_id, best_params)`；全失败不写。

返回：`{strategy_id, batch_no, total_runs, best_params, best_metric_value, succeeded, failed}`。

> **⚠️ `run_sweep_batch` 已 DEPRECATED**（change 2026-08-30-sweep-worker-queue）：端点改走下方 `worker.py` 队列，本函数不再被任何端点调用（仅测试/回退参考）。sweep.py 保留的是**参数展开纯函数**（`_expand_values` / `iter_param_ranges` / `count_param_ranges` / `extract_metric_value` 等），worker 复用 `extract_metric_value`。

### worker.py — 回测任务执行队列（strategy-worker-queue, 2026-08-30）

取代 `run_sweep_batch` 的 gather 一把梭。**single (1 行) + sweep (N 行) 统一**走此队列：EvTrade 提交时只把批次 task 行建为 `status='queued'` + 立即 202（不等执行），strategy_exec 起 worker 池执行。

`run_worker_pool(strategy_id, batch_no, user_id, script_id, stock_code, backtest_start_date, backtest_end_date, *, period="1d", concurrency=2, metric="sharpe") -> Dict`：

1. `get_batch_tasks` 校验批次存在（不存在 → RuntimeError）。
2. `fetch_his_bars` 拉一次 K 线，全批次共享。
3. `asyncio.gather(*[_worker(i) for i in range(concurrency)])` 起 N 个 worker **FIFO 有界并发**。
4. 领空后 `_finalize_batch` 读 DB 终态 → 按 `backtest_metric_value` 取 finished top1 → `update_strategy_best_params`；全失败不写。

`_worker` 循环（每 worker 独立）：
- `claim_next_queued(strategy_id, batch_no, execution_pid, gen_cap=max_retries)` **原子领取**下一个 queued task（`SELECT … FOR UPDATE SKIP LOCKED` + 乐观 `UPDATE WHERE status='queued' AND run_generation=当前`，`rowcount>0` 才算领到 → 防 N worker / 多实例抢同一 task；领取时 `run_generation+1`）。
- `asyncio.wait_for(to_thread(run_backtest, ..., run_generation=本次代际), timeout=backtest_task_timeout_seconds)` 跑回测。
- **超时自愈**：`TimeoutError` → `requeue_or_fail_on_timeout`（`run_generation >= max_retries` → 标 failed 防无限重跑；否则回 queued 待重领）；worker 复位去领下一个（**复位状态，非重启进程**）。
- 队列空（`claim` 返 None）→ 短睡 `worker_poll_interval_seconds` 再查一次（防"最后一个 task 刚被超时复位"竞态）→ 仍空则收工。

**代际隔离（孤儿线程治理）**：`to_thread` 线程杀不掉，超时复位的 task 旧线程仍在后台跑。`strategy_task.run_generation`（列，兼作代际+重跑计数）隔离：
- `run_backtest` 入口 `set_run_generation(本次代际)`（ContextVar，线程私有）
- `data_access.update_task_status` / `update_task_progress` / 结果 blob 写（`_update_task_results`）都带**代际守卫**：写前读行 `run_generation`，≠本线程代际（任务已被复位重跑，本线程是孤儿）→ **静默 no-op**，不覆盖新一次的结果/心跳
- `None`（默认）= 不过滤，兼容 live / 旧单任务路径

**逐 task 通知前端**：每个 task `run_backtest` 内 `update_task_status('finished')` → `task_progress` WS 推送（现有通道），`BatchTasksTable` 逐行刷新 status + 进度环；点任务进 `TaskDetail` 看详情。前端无需改。

config（`strategy_exec/config.py`）：`backtest_task_timeout_seconds`（默认 600s，单 task 超时阈值）、`backtest_max_retries`（默认 3，重跑上限）、`worker_poll_interval_seconds`（默认 0.5s，队列空轮询间隔）。

## 依赖关系

- 上游：`api/internal.py`（调度）、`data_access/`（脚本/任务读写）、`sandbox/loader.py`（脚本加载）、`market_data/`（历史 K 线 / WS）、`signal/publisher.py`。
- 下游：RabbitMQ `strategy.exchange`（信号）、共享 MySQL（任务/审计/最优参数）。

## 修改指南

- 加分析器（如 max_drawdown）：backtest.py 第 3 步 `cerebro.addanalyzer` + 结果提取；calmar 指标当前因缺 max_drawdown 恒 None，补 analyzer 即可激活。
- 改初始资金/手续费：backtest.py `setcash` / `setcommission`（注意前端 pnl_pct 按 100000 计算）。
- live 周期扩展：`_BarAggregator` 目前固定 1m；如需其他周期需改聚合桶逻辑。
- 改 backtest_result 结构：必须同步前端 TaskDetail.vue（best 的 signal_log/trades/win_rate + execution_log 契约；progress_log/equity_curve 已不落地）与 server `_convert.py` 的指标提取语义。
- `_wrap_strategy` 是直接改类方法（非子类），若 Backtrader 升级需验证 next()/buy_signal 钩子仍生效。
