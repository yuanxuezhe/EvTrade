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
    """bars → bt.feeds.PandasData (OHLCV)"""
    import pandas as pd

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
    if "open" not in df.columns:
        raise ValueError("bars 数据缺 'open' 列")
    return bt.feeds.PandasData(dataname=df)


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
) -> Dict[str, Any]:
    """跑一次回测, 返结果 dict (pnl / trades / signal_log)

    bars: 来自 broker his_hq 的 K 线数据 (list of dict, 含 open/high/low/close/volume/stime)

    Raises:
        SandboxViolationError / ValueError / RuntimeError
    """
    log.info("[backtest task=%d] start stock=%s bars=%d params=%s",
             task_id, stock_code, len(bars), params)

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
    _phase("load_script", f"加载脚本 script_id={script_id}")

    try:
        strategy_cls = load_strategy_class(code, ProjectStrategy)
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
    # 写 strategy_script_audit (每条 signal)
    for sig in collector.signals:
        write_audit(
            task_id=task_id,
            stime=sig.get("stime") or sig.get("ts") or datetime.now().strftime("%Y%m%d%H%M%S"),
            trd_date=backtest_start_date or "",
            phase="bar",
            trigger_type=sig.get("signal_type", "INFO"),
            stock_code=sig.get("stock_code", stock_code),
            price=sig.get("price", 0.0),
            volume=sig.get("volume", 0),
            indicators=sig.get("indicators"),
            msg=sig.get("msg", ""),
        )

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
    equity_curve = [
        {"stime": p.get("stime"), "equity": p.get("equity")}
        for p in progress_log
    ]

    # 执行日志补逐 bar 记录 (与 progress_log 同源, 数据量超限抽样, 防 JSON 膨胀)
    _MAX_BAR_ENTRIES = 2000
    if len(progress_log) > _MAX_BAR_ENTRIES:
        step = len(progress_log) / _MAX_BAR_ENTRIES
        bar_entries = [progress_log[int(i * step)] for i in range(_MAX_BAR_ENTRIES)]
    else:
        bar_entries = progress_log
    for p in bar_entries:
        exec_log.append({
            "phase": "bar",
            "bar_idx": p.get("bar_idx"),
            "stime": p.get("stime"),
            "close": p.get("close"),
            "position": p.get("position"),
            "equity": p.get("equity"),
            "msg": "",
            "ts": p.get("stime", ""),
            "elapsed_ms": 0,
        })
    _phase("done", f"回测完成 pnl={pnl:.2f} ({pnl_pct:.2f}%)")

    # 更新 strategy_task — 契约对齐前端 ScriptTask.vue:
    #   best.{signal_log, progress_log, trades, equity_curve, win_rate, trades_count, pnl, pnl_pct}
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
            "equity_curve": equity_curve,
            "signal_log": signals,
            "progress_log": progress_log,
        },
    }

    with _update_task_results(task_id, backtest_result, pnl, len(signals), best_params=params):
        update_task_status(
            task_id, "completed",
            finished_at=datetime.now().isoformat(),
            execution_pid=None,
        )

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

    逐 bar 进度 (progress_log): 每根 K 线 next() 后记录 broker 真实持仓/现金/权益,
    供前端 进度 Tab / 权益曲线 / 执行日志 Tab 展示。
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


def _update_task_results(
    task_id: int,
    backtest_result: Dict[str, Any],
    pnl: float,
    trades_count: int,
    best_params: Optional[Dict[str, Any]] = None,
):
    """上下文管理器: 写 backtest_result + best_params + pnl + trades_count (乐观锁)"""
    from contextlib import contextmanager
    from strategy_exec.data_access.db import get_session
    from sqlalchemy import text

    @contextmanager
    def ctx():
        with get_session() as s:
            # 直接 SQL (更新非 version 字段, 简单 UPDATE 不需乐观锁)
            # 但 pnl 写冲突也可能, 用乐观锁
            for attempt in range(3):
                row = s.execute(text("SELECT version FROM strategy_task WHERE id = :i"),
                                 {"i": task_id}).first()
                if row is None:
                    raise ValueError(f"task {task_id} not found")
                v = row[0]
                result = s.execute(text("""
                    UPDATE strategy_task
                       SET backtest_result = :r,
                           best_params = :bp,
                           pnl = :p,
                           trades_count = :tc,
                           version = version + 1,
                           updated_at = NOW()
                     WHERE id = :i AND version = :v
                """), {
                    "i": task_id, "v": v,
                    "r": json.dumps(backtest_result, ensure_ascii=False),
                    "bp": json.dumps(best_params or {}, ensure_ascii=False),
                    "p": pnl,
                    "tc": trades_count,
                })
                s.commit()
                if result.rowcount > 0:
                    yield
                    return
            raise RuntimeError(f"task {task_id} update result conflict")

    return ctx()