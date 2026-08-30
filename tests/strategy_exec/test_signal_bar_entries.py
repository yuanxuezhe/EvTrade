"""
test_signal_bar_entries.py — _build_signal_bar_entries 单测 (change 2026-08-30-backtest-exec-log-signal-bars)

执行日志只记「触发 buy/sell_signal 的 bar」, 不再逐 bar 全量灌入 (消息太多)。
覆盖:
  Case 1: signals 空 → 返 [] (执行日志只剩阶段时间轴)
  Case 2: 1 个 BUY 信号, stime 命中 progress_log → 查回 bar_idx/close/position/equity
  Case 3: 多信号 (BUY+SELL) 各自按 stime 对齐, msg 含 signal_type/vol/策略 msg
  Case 4: 信号 stime 查不到 progress_log → bar_idx/position/equity=None, close 兜底用 price
  Case 5: 非信号 bar 不出现 (5 根 progress_log 只 1 个信号 → 输出 1 条, 非 5 条)
  Case 6: 同 stime 多条 progress_log 取首条 (dict 覆盖语义)

策略: 纯函数, 无 DB / 无 broker 依赖, 直接构造 signals + progress_log 入参。
"""
from strategy_exec.engines.backtrader.backtest import _build_signal_bar_entries


def test_build_signal_bar_entries_empty_signals_returns_empty():
    assert _build_signal_bar_entries([], [{"stime": "20260101093100", "close": 10.0}]) == []


def test_build_signal_bar_entries_buy_hit_progress():
    signals = [{
        "signal_type": "BUY", "volume": 100, "stime": "20260101093100",
        "price": 10.0, "msg": "rsi 超买反转",
    }]
    progress = [
        {"bar_idx": 0, "stime": "20260101093000", "close": 9.9, "position": 0, "equity": 100000.0},
        {"bar_idx": 1, "stime": "20260101093100", "close": 10.0, "position": 100, "equity": 100100.0},
        {"bar_idx": 2, "stime": "20260101093200", "close": 10.1, "position": 100, "equity": 100100.0},
    ]
    out = _build_signal_bar_entries(signals, progress)
    assert len(out) == 1
    e = out[0]
    assert e["phase"] == "bar"
    assert e["bar_idx"] == 1
    assert e["stime"] == "20260101093100"
    assert e["close"] == 10.0
    assert e["position"] == 100
    assert e["equity"] == 100100.0
    assert "BUY" in e["msg"] and "100" in e["msg"] and "rsi 超买反转" in e["msg"]


def test_build_signal_bar_entries_multi_signals_align_by_stime():
    signals = [
        {"signal_type": "BUY", "volume": 100, "stime": "20260101093100", "price": 10.0, "msg": ""},
        {"signal_type": "SELL", "volume": 100, "stime": "20260101093300", "price": 10.2, "msg": "止盈"},
    ]
    progress = [
        {"bar_idx": 1, "stime": "20260101093100", "close": 10.0, "position": 100, "equity": 100100.0},
        {"bar_idx": 3, "stime": "20260101093300", "close": 10.2, "position": 0, "equity": 100200.0},
    ]
    out = _build_signal_bar_entries(signals, progress)
    assert len(out) == 2
    assert out[0]["bar_idx"] == 1 and out[0]["position"] == 100
    assert out[1]["bar_idx"] == 3 and out[1]["position"] == 0
    assert "BUY" in out[0]["msg"]
    assert "SELL" in out[1]["msg"] and "止盈" in out[1]["msg"]


def test_build_signal_bar_entries_miss_falls_back_to_price():
    signals = [{"signal_type": "SELL", "volume": 50, "stime": "20260101099999", "price": 10.5, "msg": ""}]
    progress = [{"bar_idx": 0, "stime": "20260101093000", "close": 10.0, "position": 0, "equity": 100000.0}]
    out = _build_signal_bar_entries(signals, progress)
    assert len(out) == 1
    assert out[0]["bar_idx"] is None
    assert out[0]["position"] is None
    assert out[0]["equity"] is None
    assert out[0]["close"] == 10.5  # 兜底用信号 price


def test_build_signal_bar_entries_only_signal_bars_not_all():
    # 5 根 progress_log 只有 1 个信号 → 输出 1 条 (非 5 条逐 bar)
    signals = [{"signal_type": "BUY", "volume": 100, "stime": "20260101093100", "price": 10.0, "msg": ""}]
    progress = [
        {"bar_idx": i, "stime": f"20260101093{i:02d}00", "close": 10.0, "position": 0, "equity": 100000.0}
        for i in range(5)
    ]
    # 让进度 bar 的 stime 之一正好等于信号 stime
    progress[1]["stime"] = "20260101093100"
    out = _build_signal_bar_entries(signals, progress)
    assert len(out) == 1


def test_build_signal_bar_entries_dup_stime_takes_first():
    # dict 覆盖: 同 stime 两条 progress_log, bar_idx 取后写入者 (dict 语义)
    signals = [{"signal_type": "BUY", "volume": 10, "stime": "20260101093100", "price": 10.0, "msg": ""}]
    progress = [
        {"bar_idx": 1, "stime": "20260101093100", "close": 10.0, "position": 10, "equity": 100010.0},
        {"bar_idx": 7, "stime": "20260101093100", "close": 10.0, "position": 70, "equity": 100070.0},
    ]
    out = _build_signal_bar_entries(signals, progress)
    assert out[0]["bar_idx"] == 7  # 后写覆盖
