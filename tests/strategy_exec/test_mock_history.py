"""
test_mock_history.py — strategy_exec.market_data.mock_history 单测

覆盖:
  Case 1: 5 day 区间返 5 行 (跳过 Sat/Sun)
  Case 2: 跨月/跨年区间正确
  Case 3: 同 stock_code + 同区间 = 同数据 (确定性, 跨重启一致)
  Case 4: 不同 stock_code = 不同数据
  Case 5: OHLC 关系: high >= max(open, close), low <= min(open, close)
  Case 6: volume > 0
  Case 7: stime 14 位 (YYYYMMDDHHMMSS) 对齐 broker 协议 + Backtrader 解析
  Case 8: unsupported period (1m/5m/...) 返空
  Case 9: 自定义 seed 覆盖默认 hash(stock_code)
"""
from strategy_exec.market_data.mock_history import (
    _iter_workdays,
    _seed_from_stock,
    generate_mock_bars,
)


def test_5_day_interval_returns_5_workdays():
    """20250101~20250110 跳过 Sat/Sun 后返 8 工作日 (4-5 周六日 + 8 工作日)"""
    bars = generate_mock_bars("600519.SH", "20250101", "20250110", "1d")
    assert len(bars) == 8
    # 第一根 stime 应为 20250101 (Wed)
    assert bars[0]["stime"] == "20250101150000"
    # 最后一根 stime 应为 20250110 (Fri)
    assert bars[-1]["stime"] == "20250110150000"


def test_cross_year_interval():
    """跨年区间 20241230~20250103 返 5 工作日"""
    bars = generate_mock_bars("000001.SZ", "20241230", "20250103", "1d")
    stimes = [b["stime"][:8] for b in bars]
    assert stimes == ["20241230", "20241231", "20250101", "20250102", "20250103"]


def test_same_stock_same_interval_is_deterministic():
    """同 stock_code 同区间 = 同 K 线 (跨重启一致)"""
    a = generate_mock_bars("600519.SH", "20250101", "20250110", "1d")
    b = generate_mock_bars("600519.SH", "20250101", "20250110", "1d")
    assert a == b, "确定性失败: 同 seed 应返同数据"


def test_different_stocks_have_different_data():
    """不同 stock_code = 不同数据 (hash seed 不同)"""
    a = generate_mock_bars("600519.SH", "20250101", "20250110", "1d")
    b = generate_mock_bars("000001.SZ", "20250101", "20250110", "1d")
    assert a != b, "不同 stock 应该不同"


def test_ohlc_relationships():
    """OHLC 关系: high >= max(open, close); low <= min(open, close)"""
    bars = generate_mock_bars("600519.SH", "20250101", "20250301", "1d")
    for b in bars:
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        assert h >= max(o, c), f"high 违反: {b}"
        assert l <= min(o, c), f"low 违反: {b}"
        assert l >= 0, f"low 不能为负: {b}"


def test_volume_positive():
    """volume > 0 (基线 100万 + seed 微扰)"""
    bars = generate_mock_bars("600519.SH", "20250101", "20250110", "1d")
    for b in bars:
        assert b["volume"] > 0


def test_stime_format_14_digits():
    """stime 14 位 YYYYMMDDHHMMSS (对齐 broker 协议 + Backtrader 解析)"""
    bars = generate_mock_bars("600519.SH", "20250101", "20250110", "1d")
    for b in bars:
        stime = b["stime"]
        assert len(stime) == 14, f"stime 长度应为 14, 实际 {stime}"
        assert stime.isdigit(), f"stime 应纯数字: {stime}"
        # YYYYMMDD = 前 8 位, HHMMSS = 后 6 位
        assert stime[:8] == "20250101" or stime[:8] >= "20250101"
        # 收盘时刻 15:00:00 (A股)
        assert stime[8:] == "150000", f"period=1d 应固定 15:00:00, 实际 {stime[8:]}"


def test_unsupported_period_returns_empty():
    """unsupported period (1m/5m/15m/30m/60m) 返空 (后续扩展)"""
    for period in ("1m", "5m", "15m", "30m", "60m"):
        bars = generate_mock_bars("600519.SH", "20250101", "20250110", period)
        assert bars == [], f"{period} 应返空"


def test_custom_seed_overrides_default():
    """自定义 seed 覆盖默认 hash(stock_code)"""
    a = generate_mock_bars("600519.SH", "20250101", "20250110", "1d", seed=42)
    b = generate_mock_bars("600519.SH", "20250101", "20250110", "1d", seed=42)
    assert a == b
    # 不同 seed = 不同数据
    c = generate_mock_bars("600519.SH", "20250101", "20250110", "1d", seed=43)
    assert a != c


def test_seed_from_stock_is_deterministic():
    """_seed_from_stock: 同 stock_code = 同 seed"""
    assert _seed_from_stock("600519.SH") == _seed_from_stock("600519.SH")
    # 不同 stock = 不同 seed (允许极小概率碰撞, 但通常不会)
    assert _seed_from_stock("600519.SH") != _seed_from_stock("000001.SZ") or \
        _seed_from_stock("600519.SH") != _seed_from_stock("999999.SZ")  # 至少一个不等


def test_iter_workdays_skips_weekend():
    """_iter_workdays: 跳过 Sat/Sun"""
    days = list(_iter_workdays("20250101", "20250110"))
    # 2025-01-04 Sat, 2025-01-05 Sun 跳过
    assert "20250104" not in days
    assert "20250105" not in days
    assert len(days) == 8


def test_iter_workdays_empty_for_invalid_range():
    """_iter_workdays: start > end 返空"""
    days = list(_iter_workdays("20250110", "20250101"))
    assert days == []