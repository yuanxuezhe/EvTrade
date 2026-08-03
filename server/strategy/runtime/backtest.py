"""
server/strategy/runtime/backtest.py — 回测引擎

📌 流程:
    1. 加载脚本 (sandbox)
    2. 构造 ctx (mode='backtest', sim_cash, sim_positions, lib facade, signals)
    3. on_init(ctx)
    4. 逐 bar 调 on_bar(ctx, bar), 同时维护 sim_positions / sim_cash
    5. on_finish(ctx)
    6. 解析 audit_log → trades + 计算 pnl / win_rate

📌 日志:
    - 默认 verbose=True: 每根 bar + 每个 phase 都 log.info + execution_log 收集
    - execution_log 写入 BacktestResult.execution_log, 传给前端展示
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

from server.strategy.lib import make_trading_facade, SignalRecorder
from server.strategy.runtime.sandbox import load_script, SandboxError

log = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """单笔成交 (回测)"""
    order_no: str
    stime: str
    stock_code: str
    side: str           # 'BUY' | 'SELL'
    price: float
    volume: int
    pnl: float = 0.0    # SELL 时计算 (BUY 为 0)


@dataclass
class BacktestResult:
    """回测完整结果 (写入 strategy_task.backtest_result JSON)"""
    pnl: float                              # 总已实现盈亏 (期末权益 - 期初现金, 含浮盈)
    pnl_pct: float                          # 收益率 (pnl / initial_cash)
    win_rate: float                         # 胜率 (win_count / close_count)
    trades_count: int
    final_position: int
    final_cash: float
    equity_curve: List[Dict[str, Any]]      # [{stime, equity}]
    trades: List[Dict[str, Any]]            # [BacktestTrade asdict]
    signal_log: List[Dict[str, Any]] = field(default_factory=list)   # 触发信号
    progress_log: List[Dict[str, Any]] = field(default_factory=list)  # 每根 bar 进度
    execution_log: List[Dict[str, Any]] = field(default_factory=list)  # 🆕 全阶段时间轴
    error: Optional[str] = None             # 失败原因

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────── 引擎 ───────────────


class BacktestEngine:
    """回测引擎实例

    Args:
        task_id: 用于日志关联 (None 时用 stock_code)
        verbose: True 时每根 bar 都 log.info + execution_log 收集
        on_progress: 每根 bar 处理完回调 (i, total)
        audit_enabled: True 时每次 doorder + signal() 触发都写 strategy_script_audit 行
    """

    def __init__(
        self,
        script_code: str,
        params: Dict[str, Any],
        bars: List[Dict[str, Any]],
        stock_code: str,
        initial_cash: float = 100000.0,
        period: str = "1d",
        *,
        task_id: Optional[int] = None,
        verbose: bool = True,
        audit_enabled: bool = True,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.script_code = script_code
        self.params = params
        self.bars = bars
        self.stock_code = stock_code
        self.initial_cash = initial_cash
        self.period = period
        self.task_id = task_id or 0
        self.verbose = verbose
        self.audit_enabled = audit_enabled
        self.on_progress = on_progress

        self.ctx: Dict[str, Any] = {
            "mode": "backtest",
            "symbol": stock_code,
            "period": period,
            "params": params,
            "bars": [],
            "lib": None,
            "sim_cash": initial_cash,
            "sim_initial_cash": initial_cash,
            "sim_positions": {},
            "audit_log": [],
            "signals": SignalRecorder(),
            "counter": 0,
            "current_trd_date": "",
            "state": {},
        }
        self._facade = make_trading_facade(self.ctx)
        self.ctx["lib"] = self._facade

    def run(self) -> BacktestResult:
        """执行回测 (sync, 在线程池跑)"""
        t0 = time.time()
        tag = f"[task={self.task_id}]" if self.task_id else f"[{self.stock_code}]"
        execution_log: List[Dict[str, Any]] = []

        def _log(phase: str, msg: str, **extra):
            entry = {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "phase": phase,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "msg": msg,
                **extra,
            }
            execution_log.append(entry)
            if self.verbose:
                log.info("%s [%5.1fs] %s %s", tag, time.time() - t0, phase, msg)

        _log("start", f"backtest begin: stock={self.stock_code} params={self.params} bars={len(self.bars)} period={self.period}")

        # 1. 加载脚本
        try:
            cbs = load_script(self.script_code, self.ctx, self.params)
            _log("sandbox_ok", f"compiled {len(self.script_code)} chars, callbacks={[k for k,v in cbs.items() if v]}")
        except SandboxError as e:
            _log("sandbox_err", f"sandbox error: {e}")
            return BacktestResult(
                pnl=0.0, pnl_pct=0.0, win_rate=0.0,
                trades_count=0, final_position=0, final_cash=self.initial_cash,
                equity_curve=[], trades=[], error=f"sandbox: {e}",
                execution_log=execution_log,
            )

        # 2. on_init
        if cbs["on_init"] is not None:
            try:
                _log("on_init_start", "")
                cbs["on_init"](self.ctx)
                _log("on_init_done", "")
            except Exception as e:
                _log("on_init_err", f"{e}")
                return self._err_result(f"on_init: {e}", execution_log)

        # 3. 逐 bar
        total = len(self.bars)
        equity_curve: List[Dict[str, Any]] = []
        progress_log: List[Dict[str, Any]] = []
        buy_cost_basis: Dict[str, List[tuple]] = {}
        trades: List[BacktestTrade] = []
        signals = self.ctx["signals"]

        if total == 0:
            _log("empty_bars", "no bars to process")
            return self._err_result("no bars", execution_log)

        for i, bar in enumerate(self.bars):
            bar_stime = bar.get("stime", "")
            self.ctx["bars"].append(bar)
            self.ctx["current_trd_date"] = bar_stime[:8]
            self.ctx["bar"] = bar
            self.ctx["bar_idx"] = i

            signals._current_bar_idx = i
            signals._current_stime = bar_stime

            if cbs["on_bar"] is not None:
                try:
                    cbs["on_bar"](self.ctx, bar)
                except Exception as e:
                    _log("on_bar_err", f"bar[{i}] stime={bar_stime} close={bar.get('close'):.4f}: {e}", bar_idx=i)
                    # 抛错前先把已有 audit 写库
                    self._flush_audit()
                    return self._err_result(f"on_bar[{i}]: {e}", execution_log)

            # 🆕 audit flush: 每 50 根 batch 一次 (避免每根 bar 都写库)
            if (i + 1) % 50 == 0:
                self._flush_audit()

            pos = self.ctx["sim_positions"].get(self.stock_code, 0)
            mark_price = bar.get("close", 0) or 0
            equity = self.ctx["sim_cash"] + pos * mark_price
            equity_curve.append({"stime": bar_stime, "equity": equity})

            progress_log.append({
                "bar_idx": i,
                "stime": bar_stime,
                "close": mark_price,
                "position": pos,
                "equity": round(equity, 2),
                "cash": round(self.ctx["sim_cash"], 2),
            })

            _log("bar", f"bar[{i+1}/{total}] stime={bar_stime} close={mark_price:.4f} pos={pos} eq={equity:.2f} cash={self.ctx['sim_cash']:.2f}",
                 bar_idx=i, stime=bar_stime, close=mark_price, position=pos, equity=round(equity, 2), cash=round(self.ctx["sim_cash"], 2))

            # 进度回调: 每 5% 一次 (避免每根 bar 都写 DB)
            if self.on_progress and self._should_report(i, total):
                try:
                    self.on_progress(i + 1, total)
                except Exception:
                    pass

        # 4. on_finish
        if cbs["on_finish"] is not None:
            try:
                _log("on_finish_start", "")
                cbs["on_finish"](self.ctx)
                _log("on_finish_done", "")
            except Exception as e:
                _log("on_finish_err", f"{e}")
                log.warning("on_finish 抛错 (忽略): %s", e)

        # 🆕 on_finish 后 flush 剩余 audit
        self._flush_audit()

        # 把 signals 时间戳信息合并进每条 entry
        signal_entries: List[Dict[str, Any]] = []
        for entry in signals.log:
            e = dict(entry)
            e.setdefault("stime", signals._current_stime)
            e.setdefault("bar_idx", signals._current_bar_idx)
            signal_entries.append(e)

        # 5. 解析 audit_log → trades + pnl / win_rate
        win_count = 0
        close_count = 0
        total_pnl = 0.0
        for entry in self.ctx.get("audit_log", []):
            side = entry["side"]
            price = entry["filled_price"]
            volume = entry["filled_volume"]
            stock = entry["stock_code"]
            tr = BacktestTrade(
                order_no=entry["order_no"],
                stime=entry["stime"],
                stock_code=stock, side=side,
                price=price, volume=volume,
            )
            if side == "BUY":
                buy_cost_basis.setdefault(stock, []).append((price, volume))
            else:
                cost_list = buy_cost_basis.get(stock, [])
                remaining = volume
                trade_pnl = 0.0
                while remaining > 0 and cost_list:
                    cost_price, cost_vol = cost_list[0]
                    if cost_vol <= remaining:
                        trade_pnl += (price - cost_price) * cost_vol
                        remaining -= cost_vol
                        cost_list.pop(0)
                    else:
                        trade_pnl += (price - cost_price) * remaining
                        cost_list[0] = (cost_price, cost_vol - remaining)
                        remaining = 0
                tr.pnl = trade_pnl
                total_pnl += trade_pnl
                close_count += 1
                if trade_pnl > 0:
                    win_count += 1
            trades.append(tr)

        # 6. 期末权益
        final_pos = self.ctx["sim_positions"].get(self.stock_code, 0)
        final_close = self.bars[-1]["close"] if self.bars else 0
        final_cash = self.ctx["sim_cash"]
        final_equity = final_cash + final_pos * final_close
        net_pnl = final_equity - self.initial_cash
        pnl_pct = net_pnl / self.initial_cash if self.initial_cash > 0 else 0.0
        win_rate = (win_count / close_count) if close_count > 0 else 0.0

        result = BacktestResult(
            pnl=round(net_pnl, 4),
            pnl_pct=round(pnl_pct, 4),
            win_rate=round(win_rate, 4),
            trades_count=len(trades),
            final_position=final_pos,
            final_cash=round(final_cash, 4),
            equity_curve=equity_curve,
            trades=[asdict(t) for t in trades],
            signal_log=signal_entries,
            progress_log=progress_log,
            execution_log=execution_log,
        )

        _log("done", f"backtest done: bars={total} trades={len(trades)} pnl={net_pnl:.2f} pct={pnl_pct*100:.2f}% win_rate={win_rate*100:.1f}%")

        return result

    def _err_result(self, msg: str, execution_log: Optional[List[Dict[str, Any]]] = None) -> BacktestResult:
        log.error("backtest failed: %s", msg)
        sig_log = []
        try:
            for e in self.ctx.get("signals", SignalRecorder()).log:
                e2 = dict(e)
                e2.setdefault("stime", "")
                sig_log.append(e2)
        except Exception:
            pass
        return BacktestResult(
            pnl=0.0, pnl_pct=0.0, win_rate=0.0,
            trades_count=0, final_position=0, final_cash=self.initial_cash,
            equity_curve=[], trades=[], signal_log=sig_log, progress_log=[],
            execution_log=execution_log or [],
            error=msg,
        )

    def _should_report(self, i: int, total: int) -> bool:
        """每 5% 或最后 1 根 bar 报一次 (减少 DB 写入)

        total 较小时每根都报 (单次回测)
        total >= 100 时按 5% 取整报
        """
        if total <= 100:
            return True
        threshold = max(1, total // 20)  # 5%
        return (i % threshold == 0) or (i == total - 1)

    def _flush_audit(self) -> int:
        """把当前 ctx['signals'] 里未持久化的条目写到 strategy_script_audit 表

        Returns: 写入的行数

        📌 触发场景:
            - 用户脚本调 signal(msg, type_='INFO', indicators={...}, state={...})
            - doorder 自动产生 BUY/SELL 信号
        📌 audit_enabled=False 时跳过 (测试场景)
        """
        if not self.audit_enabled or not self.task_id:
            return 0
        signals = self.ctx.get("signals")
        if signals is None or not signals.log:
            return 0

        # 用 _last_audit_idx 记录上次写到哪里,避免重复写
        if not hasattr(self, "_last_audit_idx"):
            self._last_audit_idx = 0
        new_entries = signals.log[self._last_audit_idx:]
        if not new_entries:
            return 0

        try:
            from server.tables import StrategyScriptAudit
            import json as _json
            n = 0
            for entry in new_entries:
                t = entry.get("type", "INFO")
                phase = "bar"  # 回测所有信号都在 on_bar 里产生
                stime = entry.get("stime") or signals._current_stime or ""
                trd_date = stime[:8] if stime else ""
                try:
                    # 用 add_one (纯 INSERT, 不需要 PK)
                    StrategyScriptAudit.add_one({
                        "task_id": self.task_id,
                        "stime": stime,
                        "trd_date": trd_date,
                        "phase": phase,
                        "trigger_type": t,
                        "stock_code": entry.get("stock_code") or self.stock_code,
                        "price": entry.get("price"),
                        "volume": entry.get("volume"),
                        "indicators": _json.dumps(entry.get("indicators") or {}),
                        "state": _json.dumps(entry.get("state") or {}),
                        "msg": entry.get("msg"),
                        "order_no": entry.get("order_no"),
                        "payload": _json.dumps({"bar_idx": entry.get("bar_idx")}),
                    })
                    n += 1
                except Exception as e:
                    log.warning("_flush_audit 单行失败 (忽略): %s", e)
            self._last_audit_idx += n
            if n > 0:
                log.debug("[task=%d] _flush_audit: 写入 %d 条 audit", self.task_id, n)
            return n
        except Exception as e:
            log.warning("_flush_audit 整体失败 (忽略): %s", e)
            return 0


# ─────────────── 参数组合批量回测 ───────────────


def run_grid_backtest(
    script_code: str,
    params_schema: List[Dict[str, Any]],
    bars: List[Dict[str, Any]],
    stock_code: str,
    initial_cash: float = 100000.0,
    period: str = "1d",
    sort_by: str = "pnl_pct",
    task_id: Optional[int] = None,
    verbose: bool = False,  # grid 模式默认不打 (组合多, log 爆炸)
    on_progress: Optional[Callable[[int, int, BacktestResult, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """参数组合批量回测

    Args:
        script_code: 用户脚本
        params_schema: 用户定义的参数 schema (同 grid.expand_params 输入)
        bars: 同一段历史 K 线
        stock_code, initial_cash, period: 透传给 BacktestEngine
        sort_by: 'pnl_pct' / 'pnl' / 'sharpe'
        task_id: 关联日志 (默认 verbose=False 不每根打, 防止组合爆炸)
        on_progress: 每组完成回调

    Returns:
        dict: {best_params, best_result, all_results, combinations}
    """
    from server.strategy.runtime.grid import expand_params

    combinations = expand_params(params_schema)
    all_results: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None

    log.info("grid backtest task=%s: %d combinations", task_id, len(combinations))

    for idx, params in enumerate(combinations):
        log.info("grid task=%s combo %d/%d params=%s", task_id, idx + 1, len(combinations), params)
        engine = BacktestEngine(
            script_code=script_code, params=params, bars=bars,
            stock_code=stock_code, initial_cash=initial_cash, period=period,
            task_id=task_id, verbose=verbose,
        )
        result = engine.run()
        entry = {"params": params, "result": result.to_dict()}
        all_results.append(entry)
        if best is None or result.to_dict().get(sort_by, -1e18) > best["result"].get(sort_by, -1e18):
            best = entry
        if on_progress:
            try:
                on_progress(idx + 1, len(combinations), result, params)
            except Exception:
                pass

    if best is None:
        best = {"params": {}, "result": {"error": "all combinations failed"}}

    log.info("grid task=%s done: best_params=%s best_pnl=%.2f",
             task_id, best["params"], best["result"].get("pnl", 0))

    return {
        "best_params": best["params"],
        "best_result": best["result"],
        "all_results": all_results,
        "combinations": len(combinations),
    }


__all__ = ["BacktestEngine", "BacktestResult", "run_grid_backtest"]