"""
test_backtest.py — server/strategy/runtime/backtest.py + grid.py 单元测试
"""
import pytest

from server.strategy.runtime.backtest import BacktestEngine, run_grid_backtest
from server.strategy.runtime.grid import expand_params


def make_bars(prices, period="1d"):
    bars = []
    for i, c in enumerate(prices):
        c = float(c)
        bars.append({
            "stime": f"202601{i % 9 + 1}1500",
            "open": c - 0.05, "high": c + 0.1, "low": c - 0.1, "close": c,
            "volume": 1000 + i * 100, "period": period,
        })
    return bars


# ─────────────── grid.expand_params ───────────────


class TestExpandParams:
    def test_int_grid(self):
        schema = [
            {"key": "fast", "type": "int", "min": 3, "max": 5, "step": 1},
        ]
        result = expand_params(schema)
        assert result == [{"fast": 3}, {"fast": 4}, {"fast": 5}]

    def test_cartesian(self):
        schema = [
            {"key": "fast", "type": "int", "min": 3, "max": 4, "step": 1},
            {"key": "slow", "type": "int", "min": 6, "max": 7, "step": 1},
        ]
        result = expand_params(schema)
        assert len(result) == 4
        assert {"fast": 3, "slow": 6} in result
        assert {"fast": 4, "slow": 7} in result

    def test_choice(self):
        schema = [
            {"key": "opt", "type": "choice", "values": ["a", "b", "c"]},
        ]
        result = expand_params(schema)
        assert result == [{"opt": "a"}, {"opt": "b"}, {"opt": "c"}]

    def test_over_limit(self):
        schema = [
            {"key": "fast", "type": "int", "min": 1, "max": 200, "step": 1},
            {"key": "slow", "type": "int", "min": 1, "max": 200, "step": 1},
        ]
        with pytest.raises(ValueError, match="超过上限"):
            expand_params(schema)

    def test_empty_schema(self):
        assert expand_params([]) == [{}]

    def test_float(self):
        schema = [
            {"key": "x", "type": "float", "min": 0.0, "max": 1.0, "step": 0.5},
        ]
        result = expand_params(schema)
        assert result == [{"x": 0.0}, {"x": 0.5}, {"x": 1.0}]


# ─────────────── BacktestEngine ───────────────


SAMPLE_SCRIPT = '''
def on_bar(ctx, bar):
    ma = MA(ctx['bars'], 5)
    if ma is None:
        return
    pos = ctx['state'].get('pos', 0)
    # 用户主动记录信号 (INFO 类)
    signal(f"MA5={ma:.4f} close={bar['close']:.4f}", type_='INFO')
    if bar['close'] > ma and pos == 0:
        doorder(ctx['symbol'], 'BUY', bar['close'], 100)
        ctx['state']['pos'] = 1
    elif bar['close'] < ma and pos == 1:
        doorder(ctx['symbol'], 'SELL', bar['close'], 100)
        ctx['state']['pos'] = 0
'''


class TestBacktestEngine:
    def test_basic_run(self):
        prices = [1.0 + 0.05 * i for i in range(15)] + [1.75 - 0.05 * i for i in range(15)]
        bars = make_bars(prices)

        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT,
            params={"qty": 100},
            bars=bars,
            stock_code="TEST.SH",
            initial_cash=10000.0,
        )
        result = engine.run()
        assert result.error is None, f"got error: {result.error}"
        assert result.trades_count >= 2
        sides = [t["side"] for t in result.trades]
        assert "BUY" in sides
        assert "SELL" in sides

    def test_no_trades(self):
        prices = [1.0] * 30
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="X", initial_cash=10000.0,
        )
        result = engine.run()
        assert result.trades_count == 0

    def test_syntax_error(self):
        engine = BacktestEngine(
            script_code="def on_bar(ctx, bar): return 'bad",
            params={}, bars=make_bars([1.0] * 10), stock_code="X",
        )
        result = engine.run()
        assert result.error is not None
        assert "sandbox" in result.error.lower() or "语法" in result.error

    def test_insufficient_data(self):
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=make_bars([1.0] * 3), stock_code="X",
        )
        result = engine.run()
        assert result.error is None
        assert result.trades_count == 0

    def test_equity_curve_length(self):
        prices = [1.0 + 0.01 * i for i in range(50)]
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=make_bars(prices), stock_code="X",
        )
        result = engine.run()
        assert len(result.equity_curve) == 50

    def test_run_grid_backtest(self):
        prices = [1.0 + 0.05 * i for i in range(20)]
        bars = make_bars(prices)
        schema = [
            {"key": "fast", "type": "int", "min": 3, "max": 4, "step": 1},
        ]
        result = run_grid_backtest(
            script_code=SAMPLE_SCRIPT, params_schema=schema,
            bars=bars, stock_code="X",
        )
        assert result["combinations"] == 2
        assert "best_params" in result
        assert result["best_params"]["fast"] in (3, 4)
        assert len(result["all_results"]) == 2


class TestSignalCollection:
    """信号流收集测试 — 验证 signal_log + progress_log 字段"""

    def test_signal_log_has_buy_sell_and_info(self):
        prices = [1.0 + 0.05 * i for i in range(15)] + [1.75 - 0.05 * i for i in range(15)]
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT,
            params={"qty": 100}, bars=bars, stock_code="TEST.SH", initial_cash=10000.0,
        )
        result = engine.run()
        assert result.error is None
        assert len(result.signal_log) > 0
        types = [s.get("type") for s in result.signal_log]
        assert "INFO" in types, f"应包含 INFO, 实际 {types[:10]}"
        assert "BUY" in types
        assert "SELL" in types

    def test_signal_log_stime_present(self):
        prices = [1.0 + 0.05 * i for i in range(15)] + [1.75 - 0.05 * i for i in range(15)]
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="TEST.SH", initial_cash=10000.0,
        )
        result = engine.run()
        for s in result.signal_log:
            assert "stime" in s
            assert "type" in s

    def test_progress_log_per_bar(self):
        prices = [1.0 + 0.05 * i for i in range(20)]
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="TEST.SH", initial_cash=10000.0,
        )
        result = engine.run()
        assert len(result.progress_log) == len(bars)
        for p in result.progress_log[:3]:
            assert "bar_idx" in p
            assert "stime" in p
            assert "close" in p
            assert "position" in p
            assert "equity" in p
            assert "cash" in p

    def test_signal_log_empty_on_failure(self):
        bad_script = '''
def on_bar(ctx, bar):
    raise RuntimeError("oops")
'''
        bars = make_bars([1.0] * 10)
        engine = BacktestEngine(
            script_code=bad_script, params={"qty": 100},
            bars=bars, stock_code="X", initial_cash=10000.0,
        )
        result = engine.run()
        assert result.error is not None
        assert isinstance(result.signal_log, list)
        assert isinstance(result.progress_log, list)


class TestAuditFlushing:
    """audit 写入 strategy_script_audit 测试

    用 audit_enabled=True 跑 1 次回测,验证 DB 中有 audit 行
    (用 task_id=9998 测试后清掉)
    """

    def test_audit_disabled_no_db_write(self):
        """audit_enabled=False (默认单测场景) 不写 DB"""
        prices = [1.0 + 0.05 * i for i in range(15)] + [1.75 - 0.05 * i for i in range(15)]
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="AUDIT_TEST.SH", initial_cash=10000.0,
            task_id=9998, audit_enabled=False,
        )
        result = engine.run()
        assert result.error is None
        # 信号流照常收集
        assert len(result.signal_log) > 0
        # 但 _last_audit_idx 不该存在 (因为 audit_enabled=False)
        assert not hasattr(engine, "_last_audit_idx")

    def test_audit_writes_to_db(self):
        """audit_enabled=True 时真写 strategy_script_audit (用 task_id=9999, 跑后清)"""
        from server.tables import StrategyScriptAudit
        from server.strategy.runtime.backtest import BacktestEngine as BE

        # 清掉之前测试残留
        for old in StrategyScriptAudit.query_by_fields({"task_id": 9999}):
            StrategyScriptAudit.delete_one(id=getattr(old, "_data", {}).get("id") or old.id)

        prices = [1.0 + 0.05 * i for i in range(15)] + [1.75 - 0.05 * i for i in range(15)]
        bars = make_bars(prices)
        engine = BE(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="AUDIT_TEST.SH", initial_cash=10000.0,
            task_id=9999, audit_enabled=True, verbose=False,
        )
        result = engine.run()
        assert result.error is None

        # 验证 audit 表里 task_id=9999 有数据
        audits = StrategyScriptAudit.query_by_fields({"task_id": 9999})
        assert len(audits) > 0, "audit_enabled=True 应该写到 strategy_script_audit"

        # 至少应有 1 BUY + 1 SELL + N INFO (用户 signal() 调用的)
        trigger_types = set()
        for a in audits:
            t = getattr(a, "_data", {}).get("trigger_type")
            trigger_types.add(t)

        assert "BUY" in trigger_types, f"应有 BUY 触发, 实际 {trigger_types}"
        assert "SELL" in trigger_types, f"应有 SELL 触发, 实际 {trigger_types}"
        assert "INFO" in trigger_types, f"应有 INFO 信号 (用户 signal()), 实际 {trigger_types}"

        # 验证字段:stime/trd_date/stock_code/msg
        sample = audits[0]
        sample_data = getattr(sample, "_data", {})
        assert sample_data.get("task_id") == 9999
        assert sample_data.get("stock_code") == "AUDIT_TEST.SH"
        assert sample_data.get("stime") is not None
        assert len(sample_data.get("stime", "")) >= 8  # YYYYMMDD 至少

        # 清理
        for old in StrategyScriptAudit.query_by_fields({"task_id": 9999}):
            StrategyScriptAudit.delete_one(id=getattr(old, "_data", {}).get("id") or old.id)


class TestExecutionLog:
    """execution_log 收集测试 — 用于诊断 '跑回测卡哪了'"""

    def test_execution_log_has_phase_for_each_bar(self):
        """每根 bar 都必须有 phase='bar' entry (verbose=True 默认)"""
        prices = [1.0 + 0.05 * i for i in range(15)] + [1.75 - 0.05 * i for i in range(15)]
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="TEST.SH", initial_cash=10000.0,
            task_id=42, verbose=True,
        )
        result = engine.run()
        assert result.error is None
        # 至少有 1 start + 1 sandbox_ok + 30 bar + 1 done
        phases = [e["phase"] for e in result.execution_log]
        assert "start" in phases
        assert "sandbox_ok" in phases
        assert phases.count("bar") == len(bars)
        assert "done" in phases

    def test_execution_log_bar_entry_format(self):
        """bar entry 必须含 bar_idx/stime/close/position/equity/cash"""
        prices = [1.0 + 0.05 * i for i in range(5)]
        bars = make_bars(prices)
        engine = BacktestEngine(
            script_code=SAMPLE_SCRIPT, params={"qty": 100},
            bars=bars, stock_code="TEST.SH", initial_cash=10000.0,
            task_id=99,
        )
        result = engine.run()
        bar_entries = [e for e in result.execution_log if e["phase"] == "bar"]
        assert len(bar_entries) == len(bars)
        first = bar_entries[0]
        for k in ("ts", "phase", "elapsed_ms", "msg", "bar_idx", "stime", "close", "position", "equity", "cash"):
            assert k in first, f"execution_log entry 缺 {k}: {first}"

    def test_execution_log_on_init_phases(self):
        """脚本有 on_init 时, 必须有 on_init_start + on_init_done"""
        script_with_init = '''
def on_init(ctx):
    ctx['state']['initialized'] = True

def on_bar(ctx, bar):
    if not ctx['state'].get('initialized'):
        raise RuntimeError("on_init not called!")
'''
        bars = make_bars([1.0] * 5)
        engine = BacktestEngine(
            script_code=script_with_init, params={},
            bars=bars, stock_code="X", initial_cash=10000.0,
        )
        result = engine.run()
        assert result.error is None
        phases = [e["phase"] for e in result.execution_log]
        assert "on_init_start" in phases
        assert "on_init_done" in phases

    def test_execution_log_preserved_on_error(self):
        """脚本抛错时, 已产生的 execution_log 必须保留"""
        bad_script = '''
def on_bar(ctx, bar):
    if ctx['bar_idx'] == 3:
        raise RuntimeError("simulated crash")
'''
        bars = make_bars([1.0] * 10)
        engine = BacktestEngine(
            script_code=bad_script, params={},
            bars=bars, stock_code="X", initial_cash=10000.0,
            task_id=7,
        )
        result = engine.run()
        assert result.error is not None
        # 失败时 execution_log 必须存在 + 含前 3 根 bar 的日志
        assert isinstance(result.execution_log, list)
        bar_entries = [e for e in result.execution_log if e["phase"] == "bar"]
        assert len(bar_entries) >= 3  # 至少跑到 bar_idx=2
        # 必须有 on_bar_err 阶段
        phases = [e["phase"] for e in result.execution_log]
        assert "on_bar_err" in phases




class TestProgressReporting:
    """v8.6 进度可见: BacktestEngine._should_report + on_progress 回调"""

    def test_small_total_every_bar_reported(self):
        """total <= 100 → 每根 bar 都报"""
        engine = BacktestEngine(
            SAMPLE_SCRIPT, {"qty": 100}, make_bars([1.0] * 10), "TEST.SH",
            task_id=999, audit_enabled=False,
        )
        # _should_report(i, total) for total=10
        for i in range(10):
            assert engine._should_report(i, 10) is True

    def test_large_total_5_percent(self):
        """total=1000 → 5% 报一次 (i=0, 50, 100, ...)"""
        engine = BacktestEngine(
            SAMPLE_SCRIPT, {"qty": 100}, make_bars([1.0] * 1000), "TEST.SH",
            task_id=999, audit_enabled=False,
        )
        # threshold = 1000 // 20 = 50
        assert engine._should_report(0, 1000) is True
        assert engine._should_report(49, 1000) is False
        assert engine._should_report(50, 1000) is True
        assert engine._should_report(100, 1000) is True
        # 最后一根也报
        assert engine._should_report(999, 1000) is True

    def test_on_progress_callback_invoked(self):
        """on_progress 回调至少被调一次 (5% 节点)"""
        bars = make_bars([1.0] * 20)
        progress_calls = []
        def cb(i, total):
            progress_calls.append((i, total))
        engine = BacktestEngine(
            SAMPLE_SCRIPT, {"qty": 100}, bars, "TEST.SH",
            task_id=999, audit_enabled=False, on_progress=cb,
        )
        result = engine.run()
        assert len(progress_calls) > 0
        # 最后一次是 (total, total)
        assert progress_calls[-1] == (20, 20)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])