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

    # ──── 1. 加载用户脚本 ────
    update_task_progress(task_id, {"phase": "load_script", "current": 1, "total": 4})
    script_row = get_script(user_id, script_id)
    if script_row is None:
        update_task_status(task_id, "failed", error_msg=f"script not found: ({user_id}, {script_id})")
        raise ValueError(f"script not found: ({user_id}, {script_id})")
    code = script_row["code"]

    try:
        strategy_cls = load_strategy_class(code, ProjectStrategy)
    except Exception as e:
        update_task_status(task_id, "failed", error_msg=f"sandbox load failed: {e}")
        raise

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

    # ──── 3. 注入 ProjectStrategy 元数据 + 收集 signals ────
    collector = _SignalCollector(task_id)

    # 包装 strategy: 注入元数据 + 拦截 next 中的 buy/sell_signal
    _wrap_strategy(strategy_cls, task_id, user_id, script_id, collector)

    # ──── 4. 跑回测 ────
    update_task_progress(task_id, {"phase": "running", "current": 3, "total": 4})

    try:
        results = cerebro.run()
    except Exception as e:
        update_task_status(task_id, "failed", error_msg=f"cerebro.run() failed: {e}")
        raise

    strat = results[0]
    final_value = cerebro.broker.getvalue()
    initial_cash = 100000.0
    pnl = final_value - initial_cash
    pnl_pct = pnl / initial_cash * 100

    # ──── 5. 写结果 ────
    update_task_progress(task_id, {"phase": "writing_result", "current": 4, "total": 4})

    # signal_log: collector 收集的所有 signals
    # 写 strategy_script_audit (每条 signal)
    for sig in collector.signals:
        write_audit(
            task_id=task_id,
            stime=sig.get("ts", datetime.now().isoformat()),
            trd_date=backtest_start_date or "",
            phase="bar",
            trigger_type=sig.get("signal_type", "INFO"),
            stock_code=sig.get("stock_code", stock_code),
            price=sig.get("price", 0.0),
            volume=sig.get("volume", 0),
            indicators=sig.get("indicators"),
            msg=sig.get("msg", ""),
        )

    # 更新 strategy_task
    backtest_result = {
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "final_value": final_value,
        "initial_cash": initial_cash,
        "bars_count": len(bars),
        "signal_log": collector.signals,
        "sharpe": _get_analyzer_value(strat.analyzers.sharpe.get_analysis()),
    }

    with _update_task_results(task_id, backtest_result, pnl, len(collector.signals)):
        update_task_status(
            task_id, "completed",
            finished_at=datetime.now().isoformat(),
            execution_pid=None,
        )

    log.info("[backtest task=%d] done: pnl=%.2f (%.2f%%), signals=%d",
             task_id, pnl, pnl_pct, len(collector.signals))

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
) -> None:
    """装饰用户策略类 — 注入 _set_task_meta + hook buy/sell_signal

    用 Backtrader 的 next() 包装 (override notify_order 收集)
    """
    original_init = strategy_cls.__init__
    original_next = strategy_cls.next

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._set_task_meta(task_id, user_id, script_id)

    # 装饰 buy_signal/sell_signal 自动 record 到 collector
    original_buy = strategy_cls.buy_signal
    original_sell = strategy_cls.sell_signal

    def patched_buy(self, price, volume, **kw):
        trace_id = original_buy(self, price, volume, **kw)
        if trace_id:
            collector.record({
                "signal_type": "BUY",
                "stock_code": str(self.data._name),
                "price": price,
                "volume": volume,
                "indicators": kw.get("indicators", {}),
                "msg": kw.get("msg", ""),
                "ts": datetime.now().isoformat(),
                "trace_id": trace_id,
            })
        return trace_id

    def patched_sell(self, price, volume, **kw):
        trace_id = original_sell(self, price, volume, **kw)
        if trace_id:
            collector.record({
                "signal_type": "SELL",
                "stock_code": str(self.data._name),
                "price": price,
                "volume": volume,
                "indicators": kw.get("indicators", {}),
                "msg": kw.get("msg", ""),
                "ts": datetime.now().isoformat(),
                "trace_id": trace_id,
            })
        return trace_id

    strategy_cls.__init__ = patched_init
    strategy_cls.buy_signal = patched_buy
    strategy_cls.sell_signal = patched_sell


def _update_task_results(task_id: int, backtest_result: Dict[str, Any], pnl: float, trades_count: int):
    """上下文管理器: 写 backtest_result + pnl + trades_count (乐观锁)"""
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
                    "bp": json.dumps({}, ensure_ascii=False),  # TODO: grid 时填
                    "p": pnl,
                    "tc": trades_count,
                })
                s.commit()
                if result.rowcount > 0:
                    yield
                    return
            raise RuntimeError(f"task {task_id} update result conflict")

    return ctx()