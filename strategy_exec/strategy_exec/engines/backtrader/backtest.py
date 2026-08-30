"""
strategy_exec.engines.backtrader.backtest — Backtrader 回测引擎

📌 流程:
1. 读 strategy_script.code (用户 Python)
2. sandbox loader 加载 → 返 ProjectStrategy 子类
3. 拉历史 K 线 (通过 broker his_hq RabbitMQ)
4. bt.Cerebro 加 data feed + addstrategy(cls)
5. cerebro.run() 同步跑完 → 收集 signals + 写 strategy_task

输出: 回测结果 (pnl / trades_count / signal_log) → strategy_task.backtest_result
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import backtrader as bt

from strategy_exec.data_access import (
    get_script, update_task_progress, update_task_status, write_audit,
)
# change 2026-08-30-sweep-worker-queue: 代际上下文 (worker 传 run_generation → 线程内写守卫)
from strategy_exec.data_access import set_run_generation
# change 2026-08-30-audit-batch-write: 批量 audit helper (取代逐条 write_audit)
from strategy_exec.data_access.strategy_task import write_audit_batch
from strategy_exec.engines.backtrader.adapter import ProjectStrategy
from strategy_exec.sandbox.loader import load_strategy_class

log = logging.getLogger(__name__)


class _SignalCollector:
    """Backtrader 期间收集 signals (sandbox 内的 buy_signal/sell_signal 调用)"""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        self.signals: List[Dict[str, Any]] = []

    def record(self, payload: Dict[str, Any]) -> None:
        self.signals.append(payload)


def _make_pandas_data_feed(bars: List[Dict[str, Any]]):
    """bars → bt.feeds.PandasData (OHLCV)

    change 2026-08-30-his-hq-cache-minute-bars:
    - broker stub 可能返 '0.0' 占位 open/high/low, Backtrader 算指标 NaN
    - 改为: open 列全 NaN 时用 close 列填充 (无 raise)
    - close 列全 NaN 时 raise (保留原报错, 但极少见)
    """
    import pandas as pd
    from backtrader import feeds

    df = pd.DataFrame(bars)
    # 标准化列名
    rename = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # broker his_hq 返回的 OHLCV 是字符串, Backtrader 需要 numeric
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # stime → datetime
    if "stime" in df.columns:
        df["dt"] = pd.to_datetime(df["stime"], format="%Y%m%d%H%M%S", errors="coerce")
        df = df.set_index("dt")
    # change 2026-08-30-his-hq-cache-minute-bars: open NaN 用 close 兜底
    if "open" not in df.columns:
        if "close" not in df.columns:
            raise ValueError("bars 数据缺 'open' 列 (且无 close 列可兜底)")
        # close 列也在 → 用 close 兜底 open (避免 Backtrader 计算 NaN)
        import logging
        log = logging.getLogger(__name__)
        log.warning("[backtest] bars 缺 'open' 列, 用 'close' 列兜底 (%d bars)", len(df))
        df["open"] = df["close"]
    elif df["open"].isna().all() and "close" in df.columns:
        # open 列全 NaN → 用 close 兜底
        import logging
        log = logging.getLogger(__name__)
        log.warning("[backtest] bars 'open' 列全 NaN, 用 'close' 列兜底 (%d bars)", len(df))
        df["open"] = df["close"]
    # high/low 同理兜底
    for col in ("high", "low"):
        if col not in df.columns:
            if "close" in df.columns:
                df[col] = df["close"]
        elif df[col].isna().all() and "close" in df.columns:
            df[col] = df["close"]
    # volume: 缺则补 0 (Backtrader 不要求 volume 非空)
    if "volume" not in df.columns:
        df["volume"] = 0
    elif df["volume"].isna().any():
        df["volume"] = df["volume"].fillna(0)
    return feeds.PandasData(dataname=df)


def run_backtest(
    task_id: int,
    user_id: int,
    script_id: str,
    stock_code: str,
    params: Dict[str, Any],
    bars: List[Dict[str, Any]],
    backtest_start_date: Optional[str] = None,
    backtest_end_date: Optional[str] = None,
    period: str = "1d",
    strategy_id: Optional[int] = None,
    update_strategy_best: bool = False,
    run_generation: Optional[int] = None,
) -> Dict[str, Any]:
    """跑一次回测, 返结果 dict (pnl / trades / signal_log)

    bars: 来自 broker his_hq 的 K 线数据 (list of dict, 含 open/high/low/close/volume/stime)

    - strategy_id: 任务所属策略 (仅用于回写 best_params 定位)
    - update_strategy_best: True=本次回测成功后把 params 写 strategy.best_params
      (单次回测=True; 扫描批次内组合任务=False, best 由 sweep engine 统一回写)
    - run_generation: worker 领取时的代际 (change 2026-08-30-sweep-worker-queue)。非 None 时,
      本次线程内所有 status/progress 写都带代际守卫 — 任务被复位重跑后, 本线程(旧代际)晚到的
      写会被 data_access 静默丢弃 (防孤儿线程覆盖新一次结果)。None = 不过滤 (live/旧单任务路径)。

    Raises:
        SandboxViolationError / ValueError / RuntimeError
    """
    if run_generation is not None:
        set_run_generation(run_generation)
    log.info("[backtest task=%d] start stock=%s bars=%d params=%s gen=%s",
             task_id, stock_code, len(bars), params, run_generation)

    update_task_status(task_id, "running", execution_pid=_get_pid())

    # 执行日志 (阶段时间轴 + 逐 bar 记录, 前端 ScriptTask.vue 执行日志 Tab 消费)
    exec_log: List[Dict[str, Any]] = []
    _t0 = time.time()

    def _phase(name: str, msg: str = "") -> None:
        exec_log.append({
            "phase": name,
            "msg": msg,
            "ts": datetime.now().isoformat(),
            "elapsed_ms": int(round((time.time() - _t0) * 1000)),
        })

    _phase("start", f"回测启动 stock={stock_code} bars={len(bars)}")

    # ──── 1. 加载用户脚本 ────
    update_task_progress(task_id, {"phase": "load_script", "current": 1, "total": 4})
    script_row = get_script(user_id, script_id)
    if script_row is None:
        update_task_status(task_id, "failed", error_msg=f"script not found: ({user_id}, {script_id})")
        raise ValueError(f"script not found: ({user_id}, {script_id})")
    code = script_row["code"]
    params_schema = script_row.get("params_schema") or None
    _phase("load_script", f"加载脚本 script_id={script_id}")

    try:
        strategy_cls = load_strategy_class(code, ProjectStrategy, params_schema=params_schema)
    except Exception as e:
        update_task_status(task_id, "failed", error_msg=f"sandbox load failed: {e}")
        raise
    _phase("sandbox_ok", "sandbox 加载成功")

    # ──── 2. 构造 Backtrader ────
    update_task_progress(task_id, {"phase": "build_cerebro", "current": 2, "total": 4})

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **params)

    # data feed
    data = _make_pandas_data_feed(bars)
    data._name = stock_code  # ProjectStrategy 用 self.data._name 取 stock_code
    cerebro.adddata(data)

    # broker 初始资金
    cerebro.broker.setcash(100000.0)
    # 手续费 0 (简化; 实盘 EvTrade 算)
    cerebro.broker.setcommission(commission=0.0)

    # analyzers
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
    _phase("build_cerebro", f"构造 Cerebro (bars={len(bars)}, params={params})")

    # ──── 3. 注入 ProjectStrategy 元数据 + 收集 signals / 逐 bar 进度 ────
    collector = _SignalCollector(task_id)
    progress_log: List[Dict[str, Any]] = []

    # 包装 strategy: 注入元数据 + 拦截 buy/sell_signal + 采集逐 bar 进度
    _wrap_strategy(strategy_cls, task_id, user_id, script_id, collector, progress_log, total_bars=len(bars))

    # ──── 4. 跑回测 ────
    update_task_progress(task_id, {"phase": "running", "current": 3, "total": 4})
    _phase("running", f"cerebro.run() 开始, 共 {len(bars)} 根 K 线")

    try:
        results = cerebro.run()
    except Exception as e:
        update_task_status(task_id, "failed", error_msg=f"cerebro.run() failed: {e}")
        raise
    _phase("running_done", f"cerebro.run() 完成, 触发信号 {len(collector.signals)} 条")

    strat = results[0]
    final_value = cerebro.broker.getvalue()
    initial_cash = 100000.0
    pnl = final_value - initial_cash
    pnl_pct = pnl / initial_cash * 100

    # ──── 5. 写结果 ────
    update_task_progress(task_id, {"phase": "writing_result", "current": 4, "total": 4})
    _phase("writing_result", f"写结果 pnl={pnl:.2f} ({pnl_pct:.2f}%) signals={len(collector.signals)}")

    # signal_log: collector 收集的所有 signals
    # change 2026-08-30-audit-batch-write: 收集 → write_audit_batch 批量 INSERT (vs 原逐条 write_audit)
    # 实测 12,040 signals: 单条 6 min+ → batch ~12s (60x speedup)
    audit_rows = []
    for sig in collector.signals:
        audit_rows.append({
            "task_id": task_id,
            "stime": sig.get("stime") or sig.get("ts") or datetime.now().strftime("%Y%m%d%H%M%S"),
            "trd_date": backtest_start_date or "",
            "phase": "bar",
            "trigger_type": sig.get("signal_type", "INFO"),
            "stock_code": sig.get("stock_code", stock_code),
            "price": sig.get("price", 0.0),
            "volume": sig.get("volume", 0),
            "indicators": sig.get("indicators"),
            "msg": sig.get("msg", ""),
        })
    write_audit_batch(audit_rows)

    signals = collector.signals
    # 由 signals 派生 trades / win_rate (交易明细 Tab)
    trades = [
        {
            "stime": sig.get("stime"),
            "side": sig.get("signal_type"),
            "price": sig.get("price"),
            "volume": sig.get("volume"),
            "pnl": round(float(sig.get("pnl", 0.0) or 0.0), 2),
        }
        for sig in signals
    ]
    sells = [s for s in signals if s.get("signal_type") == "SELL"]
    wins = [s for s in sells if (s.get("pnl") or 0) > 0]
    win_rate = round(len(wins) / len(sells), 4) if sells else 0.0

    # change 2026-08-30-drop-fullbar-progress: 不再逐 bar 全量落库 (progress_log/equity_curve)。
    # progress_log 仅作为本次 run 的**内存缓冲**: 供 _build_signal_bar_entries 取触发信号 bar 的
    # equity/close/position (写进 execution_log)。回测结束即丢弃, 不进 backtest_result。
    exec_log.extend(_build_signal_bar_entries(signals, progress_log))
    _phase("done", f"回测完成 pnl={pnl:.2f} ({pnl_pct:.2f}%)")

    # 更新 strategy_task — 契约对齐前端 TaskDetail.vue:
    #   best.{signal_log, trades, win_rate, trades_count, pnl, pnl_pct}
    #   逐 bar 全量 (progress_log/equity_curve) 已删; 权益曲线改用 execution_log 信号 bar 的 {stime, equity}。
    #   pnl_pct / win_rate 存小数 (前端 *100 得百分比); 顶层 summary 兼容历史
    backtest_result = {
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "final_value": final_value,
        "initial_cash": initial_cash,
        "bars_count": len(bars),
        "sharpe": _get_analyzer_value(strat.analyzers.sharpe.get_analysis()),
        "signal_log": signals,
        "total_bars": len(bars),
        "execution_log": exec_log,
        "best": {
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / initial_cash, 6),
            "win_rate": win_rate,
            "trades_count": len(signals),
            "trades": trades,
            "signal_log": signals,
        },
    }

    with _update_task_results(task_id, backtest_result, pnl, len(signals)):
        update_task_status(
            task_id, "finished",  # 终态统一 'finished' (设计契约, list_batches 聚合)
            finished_at=datetime.now().isoformat(),
            execution_pid=None,
        )

    # 单次回测成功后把本次 params 回写 strategy.best_params
    # (扫描批次不在这写 — sweep engine 按批次内 finished tasks 排序统一回写 top1)
    if update_strategy_best and strategy_id:
        from strategy_exec.data_access import update_strategy_best_params
        try:
            update_strategy_best_params(strategy_id, params)
        except Exception as e:
            log.warning("[backtest task=%d] write strategy.best_params failed: %s",
                        task_id, e)

    log.info("[backtest task=%d] done: pnl=%.2f (%.2f%%), signals=%d",
             task_id, pnl, pnl_pct, len(signals))

    return backtest_result


def _get_pid() -> Optional[int]:
    """当前进程 pid"""
    import os
    return os.getpid()


def _get_analyzer_value(d: Dict[str, Any]) -> Optional[float]:
    """Sharpe ratio analyzer 返 dict, 取 sharperatio 字段"""
    if not d:
        return None
    v = d.get("sharperatio")
    if v is None or v == 0.0:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build_signal_bar_entries(
    signals: List[Dict[str, Any]],
    progress_log: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """执行日志的 bar 段 — 只取「触发 buy/sell_signal 的 K 线」 (非逐 bar 全量)。

    遍历 signals, 每条按 stime 从 progress_log 查回 bar_idx/close/position/equity
    (供 TaskDetail.vue 列渲染), 拼一条 phase="bar" 记录。

    change 2026-08-30-drop-fullbar-progress: progress_log 现在是**逐 bar 内存缓冲** (不落地),
    仅服务于本函数取信号 bar 的快照; 用完即弃, 不进 backtest_result / 权益曲线。

    - signals 空 → 返 [] (执行日志只剩阶段时间轴)。
    - 信号 stime 在 progress_log 查不到 → bar_idx/position/equity=None, close 兜底用信号 price。
    """
    prog_by_stime = {p.get("stime"): p for p in progress_log if p.get("stime")}
    entries: List[Dict[str, Any]] = []
    for sig in signals:
        stime = sig.get("stime") or ""
        prog = prog_by_stime.get(stime)
        sig_msg = (sig.get("msg") or "").strip()
        exec_msg = f"{sig.get('signal_type', '?')} vol={sig.get('volume', '')}"
        if sig_msg:
            exec_msg += f" ({sig_msg})"
        entries.append({
            "phase": "bar",
            "bar_idx": prog.get("bar_idx") if prog else None,
            "stime": stime,
            "close": prog.get("close") if prog else sig.get("price"),
            "position": prog.get("position") if prog else None,
            "equity": prog.get("equity") if prog else None,
            "msg": exec_msg,
            "ts": stime,
            "elapsed_ms": 0,
        })
    return entries


def _wrap_strategy(
    strategy_cls: type,
    task_id: int,
    user_id: int,
    script_id: str,
    collector: _SignalCollector,
    progress_log: Optional[List[Dict[str, Any]]] = None,
    total_bars: int = 0,
) -> None:
    """装饰用户策略类 — 注入 _set_task_meta + hook buy/sell_signal + 采集逐 bar 进度

    逐 bar 进度 (progress_log): 每根 K 线 next() 后记录 broker 真实持仓/现金/权益。
    **内存缓冲, 不落地** — 仅供 _build_signal_bar_entries 取触发信号 bar 的快照写进
    execution_log (权益曲线已改用 execution_log 信号 bar), 回测结束即丢弃。
    节流上报 (bar_idx/total_bars → task.progress): 长回测时前端进度条实时走动。
    """
    original_init = strategy_cls.__init__
    original_next = strategy_cls.next
    _progress = progress_log if progress_log is not None else []
    _last_prog_ts = {"t": 0.0}  # 节流: 至少间隔 0.5s 才上报一次进度

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._set_task_meta(task_id, user_id, script_id, mode="backtest")

    def patched_next(self):
        original_next(self)
        try:
            pos = (self.position.size if self.position else 0) or 0
            _progress.append({
                "bar_idx": len(_progress),
                "stime": self._bar_time(),
                "close": float(self.data.close[0]) if self.data.close[0] is not None else 0.0,
                "position": pos,
                "cash": round(self.broker.getcash(), 2) if self.broker else 0.0,
                "equity": round(self.broker.getvalue(), 2) if self.broker else 0.0,
            })
            # 节流上报回测进度 (长回测时前端进度条实时走动)
            if total_bars and time.time() - _last_prog_ts["t"] >= 0.5:
                _last_prog_ts["t"] = time.time()
                try:
                    update_task_progress(task_id, {
                        "phase": "running",
                        "bar_idx": len(_progress),
                        "total_bars": total_bars,
                    })
                except Exception:
                    pass
        except Exception:
            pass

    # 装饰 buy_signal/sell_signal 自动 record 到 collector.
    # 关键: 回测里信号=真实成交 → 同时下 backtrader 订单 (下一 bar 按市价成交),
    # 这样 broker 持仓/现金/盈亏会真实累积, 前端也能看到每条信号的 state/pnl.
    original_buy = strategy_cls.buy_signal
    original_sell = strategy_cls.sell_signal
    pos_tracker = {"size": 0, "avg": 0.0}  # 长仓口径的持仓/均价跟踪

    def patched_buy(self, price, volume, **kw):
        trace_id = original_buy(self, price, volume, **kw)
        if trace_id:
            self.buy(size=volume)  # 回测真实成交: 市价单, 下一 bar 成交
            p = float(price)
            old_size = pos_tracker["size"]
            pos_tracker["avg"] = (old_size * pos_tracker["avg"] + volume * p) / (old_size + volume)
            pos_tracker["size"] = old_size + volume
            collector.record({
                "signal_type": "BUY",
                "stock_code": str(self.data._name),
                "price": price,
                "volume": volume,
                "indicators": kw.get("indicators", {}),
                "msg": kw.get("msg", ""),
                "ts": datetime.now().strftime("%Y%m%d%H%M%S"),
                "stime": self._bar_time(),  # 触发信号的 K 线时间
                "mode": "backtest",         # 回测信号 = 模拟成交 (不下真实单)
                "state": {"position": pos_tracker["size"],
                          "cash": round(self.broker.getcash() - volume * p, 2)},  # 成交后估算现金
                "pnl": 0.0,                 # 买入不实现盈亏
                "trace_id": trace_id,
            })
        return trace_id

    def patched_sell(self, price, volume, **kw):
        trace_id = original_sell(self, price, volume, **kw)
        if trace_id:
            self.sell(size=volume)  # 回测真实成交: 市价单, 下一 bar 成交
            p = float(price)
            close_vol = min(volume, pos_tracker["size"])
            realized = (p - pos_tracker["avg"]) * close_vol if close_vol > 0 else 0.0
            pos_tracker["size"] -= close_vol
            if pos_tracker["size"] <= 0:
                pos_tracker["size"] = 0
                pos_tracker["avg"] = 0.0
            collector.record({
                "signal_type": "SELL",
                "stock_code": str(self.data._name),
                "price": price,
                "volume": volume,
                "indicators": kw.get("indicators", {}),
                "msg": kw.get("msg", ""),
                "ts": datetime.now().strftime("%Y%m%d%H%M%S"),
                "stime": self._bar_time(),  # 触发信号的 K 线时间
                "mode": "backtest",         # 回测信号 = 模拟成交 (不下真实单)
                "state": {"position": pos_tracker["size"],
                          "cash": round(self.broker.getcash() + volume * p, 2)},  # 成交后估算现金
                "pnl": round(realized, 2),  # 卖出实现盈亏
                "trace_id": trace_id,
            })
        return trace_id

    strategy_cls.__init__ = patched_init
    strategy_cls.next = patched_next
    strategy_cls.buy_signal = patched_buy
    strategy_cls.sell_signal = patched_sell


def _metric_value_from_result(backtest_result: Dict[str, Any]) -> Optional[float]:
    """从 backtest_result 提取展示用指标值 (持久化到 backtest_metric_value 列).

    语义必须与 server/services/script_strategy/_convert.py 的
    _extract_metric_value 一致 (列表接口按此列展示指标, 不再解析大 blob):
    sharpe → total_return → pnl/initial_cash 回退.
    """
    if not backtest_result or not isinstance(backtest_result, dict):
        return None
    for key in ("sharpe", "total_return"):
        if backtest_result.get(key) is not None:
            try:
                return float(backtest_result[key])
            except (TypeError, ValueError):
                pass
    pnl = backtest_result.get("pnl")
    cash = backtest_result.get("initial_cash") or 100000.0
    if pnl is not None and cash:
        try:
            return float(pnl) / float(cash)
        except (TypeError, ValueError):
            pass
    return None


def _update_task_results(
    task_id: int,
    backtest_result: Dict[str, Any],
    pnl: float,
    trades_count: int,
):
    """上下文管理器: 写 backtest_result + pnl + trades_count + 指标值 (乐观锁)

    strategy_task 无 best_params 列, best 回写 strategy.best_params
    (见 run_backtest 的 update_strategy_best 分支 / sweep engine).
    backtest_metric_value: 轻量指标列 — 列表接口 SELECT 白名单免拖回大 blob,
    规避 MySQL 1038 'Out of sort memory'.
    """
    from contextlib import contextmanager
    from strategy_exec.data_access.db import get_session
    from strategy_exec.data_access import get_run_generation
    from sqlalchemy import text

    metric_value = _metric_value_from_result(backtest_result)
    # change 2026-08-30-sweep-worker-queue: 代际守卫 — 结果 blob 走直接 SQL (绕过 update_task_status),
    # 必须单独判: 若 task 当前 run_generation 已 != 本线程代际 (被复位重跑, 本线程是孤儿) → 跳过,
    # 防旧 run 的 backtest_result/pnl 覆盖新一次。gen=None (live/旧单任务) 不过滤。
    gen = get_run_generation()

    @contextmanager
    def ctx():
        with get_session() as s:
            # 直接 SQL (更新非 version 字段, 简单 UPDATE 不需乐观锁)
            # 但 pnl 写冲突也可能, 用乐观锁
            for attempt in range(3):
                row = s.execute(text(
                    "SELECT version, run_generation FROM strategy_task WHERE id = :i"
                ), {"i": task_id}).first()
                if row is None:
                    raise ValueError(f"task {task_id} not found")
                v = row[0]
                if gen is not None and row[1] != gen:
                    log.warning("[backtest task=%d] result write skipped (stale gen thread=%s row=%s) — orphan",
                                task_id, gen, row[1])
                    yield
                    return
                result = s.execute(text("""
                    UPDATE strategy_task
                       SET backtest_result = :r,
                           pnl = :p,
                           trades_count = :tc,
                           backtest_metric_value = :mv,
                           version = version + 1,
                           updated_at = NOW()
                     WHERE id = :i AND version = :v
                """), {
                    "i": task_id, "v": v,
                    "r": json.dumps(backtest_result, ensure_ascii=False),
                    "p": pnl,
                    "tc": trades_count,
                    "mv": metric_value,
                })
                s.commit()
                if result.rowcount > 0:
                    yield
                    return
            raise RuntimeError(f"task {task_id} update result conflict")

    return ctx()