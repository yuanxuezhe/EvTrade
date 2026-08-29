"""
test_aggregator.py — strategy_exec.market_data.aggregator 单测

覆盖:
  Case 1: 1m 透传 (无聚合)
  Case 2: 5m 桶对齐 (5 根 1m → 1 根 5m)
  Case 3: 15m / 30m / 60m 桶对齐
  Case 4: 1d A股聚合 (跨周末跳过)
  Case 5: 1d 单日 (周五)
  Case 6: 边界: 5 根 1m 边界 09:31 → 09:30 桶
  Case 7: 边界: empty / 0 rows 返 []
  Case 8: 边界: 跨日 stime 解析
  Case 9: OHLCV 计算正确 (open=首, close=末, high=max, low=min, volume=sum)
  Case 10: volume 兜底 (broker 不返 → 0)
  Case 11: 1h alias (60m 同)
  Case 12: unsupported period 抛 ValueError

策略: 纯函数测试, 无 IO, 无 mock
"""
import datetime as dt

import pytest

from strategy_exec.market_data.aggregator import (
    _aggregate_1d,
    _aggregate_intraday,
    _bucket_key,
    _format_stime,
    _parse_stime,
    aggregate_bars,
)


# ─────────────── Case 1: 1m 透传 ───────────────


def test_1m_passthrough():
    """1m 透传, 无聚合"""
    bars_1m = [
        {"stime": "20250102093100", "close": "100.0"},
        {"stime": "20250102093200", "close": "101.0"},
        {"stime": "20250102093300", "close": "102.0"},
    ]
    out = aggregate_bars(bars_1m, "1m")
    assert len(out) == 3
    # 1m 透传, open/high/low 用 close 兜底 (broker 1m 不返)
    for i, b in enumerate(out):
        assert b["open"] == float(bars_1m[i]["close"])
        assert b["close"] == float(bars_1m[i]["close"])


# ─────────────── Case 2: 5m 桶对齐 ───────────────


def test_5m_bucket_alignment():
    """5 根 1m (09:31-09:35) → 2 个 5m 桶 (09:30 桶含 09:31/32/33, 09:35 桶含 09:34/35)"""
    bars_1m = [
        {"stime": "20250102093100", "close": "100.0"},  # 09:30 桶
        {"stime": "20250102093200", "close": "101.0"},  # 09:30 桶
        {"stime": "20250102093300", "close": "102.0"},  # 09:30 桶
        {"stime": "20250102093400", "close": "103.0"},  # 09:30 桶 (34 // 5 = 6, 6*5=30)
        {"stime": "20250102093500", "close": "104.0"},  # 09:35 桶
    ]
    out = aggregate_bars(bars_1m, "5m")
    assert len(out) == 2, f"5m 应分 2 桶, 实际 {len(out)}"
    # 09:30 桶: open=100, close=103, high=103, low=100
    assert out[0]["stime"] == "20250102093000"
    assert out[0]["open"] == 100.0
    assert out[0]["high"] == 103.0
    assert out[0]["low"] == 100.0
    assert out[0]["close"] == 103.0
    # 09:35 桶: 单根 close=104
    assert out[1]["stime"] == "20250102093500"
    assert out[1]["close"] == 104.0


# ─────────────── Case 3: 15m / 30m / 60m ───────────────


def test_15m_aggregation():
    """15 根 1m (1 个 15m 桶)"""
    bars_1m = [{"stime": f"2025010209{30 + i:02d}00", "close": str(100.0 + i)} for i in range(15)]
    out = aggregate_bars(bars_1m, "15m")
    assert len(out) == 1
    assert out[0]["stime"] == "20250102093000"  # 09:30 桶
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 114.0
    assert out[0]["high"] == 114.0
    assert out[0]["low"] == 100.0


def test_30m_aggregation():
    """30 根 1m (1 个 30m 桶)"""
    bars_1m = [{"stime": f"2025010209{30 + i:02d}00", "close": str(100.0 + i)} for i in range(30)]
    out = aggregate_bars(bars_1m, "30m")
    assert len(out) == 1
    assert out[0]["stime"] == "20250102093000"
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 129.0


def test_60m_aggregation():
    """60 根 1m (09:00~09:59) → 1 个 60m 桶 (09:00 桶)"""
    bars_1m = [
        {"stime": f"2025010209{i // 60:02d}{i % 60:02d}00", "close": str(100.0 + i)}
        for i in range(60)
    ]
    out = aggregate_bars(bars_1m, "60m")
    assert len(out) == 1
    assert out[0]["stime"] == "20250102090000"
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 159.0


def test_1h_alias_60m():
    """1h 是 60m 的 alias"""
    bars_1m = [
        {"stime": f"2025010209{i // 60:02d}{i % 60:02d}00", "close": str(100.0 + i)}
        for i in range(60)
    ]
    out = aggregate_bars(bars_1m, "1h")
    assert len(out) == 1
    assert out[0]["stime"] == "20250102090000"


# ─────────────── Case 4: 1d A股聚合 (跨周末跳过) ───────────────


def test_1d_aggregate_skips_weekend():
    """跨 Sat/Sun → 只返 3 个 1d (周一/二/三, Sat 跳过, Sun 跳过, 周一 next week 保留)"""
    # 2025-01-02 Thu, 01-03 Fri, 01-04 Sat, 01-05 Sun, 01-06 Mon
    bars_1d = [
        {"stime": f"20250102{hh}{mm}00", "close": str(c)}
        for hh, mm, c in [("09", "31", 100), ("15", "00", 105)]
    ] + [
        {"stime": f"20250103{hh}{mm}00", "close": str(c)}
        for hh, mm, c in [("09", "31", 106), ("15", "00", 110)]
    ] + [
        {"stime": f"20250104{hh}{mm}00", "close": str(c)}  # Sat — 应跳过
        for hh, mm, c in [("09", "31", 111), ("15", "00", 115)]
    ] + [
        {"stime": f"20250106{hh}{mm}00", "close": str(c)}  # Mon next week
        for hh, mm, c in [("09", "31", 112), ("15", "00", 118)]
    ]
    out = aggregate_bars(bars_1d, "1d")
    assert len(out) == 3, f"应 3 个 1d (Thu/Fri/Mon, 跳过 Sat), 实际 {len(out)}"
    assert out[0]["stime"] == "20250102150000"
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 105.0
    assert out[1]["stime"] == "20250103150000"
    assert out[1]["close"] == 110.0
    assert out[2]["stime"] == "20250106150000"
    assert out[2]["close"] == 118.0


def test_1d_single_day():
    """单日 1d 聚合 → 1 根 1d K 线"""
    bars_1m = [
        {"stime": "20250102093100", "close": "100.0"},
        {"stime": "20250102113000", "close": "102.0"},  # 11:30 (早盘结束)
        {"stime": "20250102130100", "close": "101.0"},  # 13:01 (午盘开始)
        {"stime": "20250102150000", "close": "105.0"},  # 15:00 (收盘)
    ]
    out = aggregate_bars(bars_1m, "1d")
    assert len(out) == 1
    assert out[0]["stime"] == "20250102150000"
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 105.0
    assert out[0]["high"] == 105.0
    assert out[0]["low"] == 100.0


# ─────────────── Case 5: OHLCV 计算正确 ───────────────


def test_ohlcv_calculation_correct():
    """5 根 1m → OHLCV: open=首根, close=末根, high=max, low=min, volume=sum"""
    bars_1m = [
        {"stime": "20250102093100", "open": "100.0", "high": "105.0", "low": "99.0", "close": "102.0", "volume": "1000"},
        {"stime": "20250102093200", "open": "102.0", "high": "103.0", "low": "101.0", "close": "101.0", "volume": "2000"},
        {"stime": "20250102093300", "open": "101.0", "high": "104.0", "low": "100.0", "close": "103.0", "volume": "1500"},
    ]
    # 5m 聚合 (3 根都在 09:30 桶, 09:31-09:33)
    out = aggregate_bars(bars_1m, "5m")
    assert len(out) == 1
    # 5m 用 1m 数据, broker 1m 返 close + 0/缺 OHLV, aggregator fallback 到 close
    # 实际: broker 1m 只返 close, 高开低都用 close 兜底
    # 这里测 5m 直接用输入 open/high/low (因为 _aggregate_intraday 用 bars 原值)
    assert out[0]["open"] == 100.0  # 第一根 open
    assert out[0]["high"] == 105.0  # 3 根 high max
    assert out[0]["low"] == 99.0  # 3 根 low min
    assert out[0]["close"] == 103.0  # 末根 close
    assert out[0]["volume"] == 4500  # 1000+2000+1500


# ─────────────── Case 6: volume 兜底 ───────────────


def test_volume_defaults_to_zero_when_missing():
    """broker 1m 不返 volume → aggregator 输出 volume=0 (不造数据)"""
    bars_1m = [
        {"stime": "20250102093100", "close": "100.0"},
        {"stime": "20250102093200", "close": "101.0"},
    ]
    out = aggregate_bars(bars_1m, "5m")
    assert out[0]["volume"] == 0


# ─────────────── Case 7: empty / 0 rows ───────────────


def test_empty_bars_returns_empty():
    """empty input → []"""
    for period in ("1m", "5m", "1d"):
        assert aggregate_bars([], period) == [], f"{period} 应返 []"


# ─────────────── Case 8: 跨日 stime ───────────────


def test_intraday_aggregation_does_not_cross_day():
    """跨日 1m 数据, 5m 聚合按时间桶 (不按日期分桶)"""
    bars_1m = [
        {"stime": "20250102233500", "close": "100.0"},  # 23:35 桶
        {"stime": "20250102234000", "close": "101.0"},  # 23:40 桶
        {"stime": "20250103000100", "close": "102.0"},  # 00:00 桶 (next day)
    ]
    out = aggregate_bars(bars_1m, "5m")
    # 应 3 桶 (跨日期也分桶)
    assert len(out) == 3


# ─────────────── Case 9: 5m 桶边界 ───────────────


def test_5m_bucket_key_alignment():
    """桶对齐: 09:30 / 09:35 / 09:40, 09:31→09:30, 09:36→09:35"""
    assert _bucket_key(dt.datetime(2025, 1, 2, 9, 31), 5) == dt.datetime(2025, 1, 2, 9, 30)
    assert _bucket_key(dt.datetime(2025, 1, 2, 9, 35), 5) == dt.datetime(2025, 1, 2, 9, 35)
    assert _bucket_key(dt.datetime(2025, 1, 2, 9, 36), 5) == dt.datetime(2025, 1, 2, 9, 35)
    assert _bucket_key(dt.datetime(2025, 1, 2, 9, 40), 5) == dt.datetime(2025, 1, 2, 9, 40)
    assert _bucket_key(dt.datetime(2025, 1, 2, 9, 0), 5) == dt.datetime(2025, 1, 2, 9, 0)


# ─────────────── Case 10: stime 格式 ───────────────


def test_stime_format_intraday():
    """intraday (5m/15m/30m/60m) stime 输出 YYYYMMDDHHMMSS (14 位, 桶起点)"""
    bars_1m = [{"stime": "20250102093100", "close": "100.0"}]
    out = aggregate_bars(bars_1m, "5m")
    assert out[0]["stime"] == "20250102093000"  # 14 位
    assert len(out[0]["stime"]) == 14


def test_stime_format_1d():
    """1d stime 输出 YYYYMMDD150000 (14 位, 收盘时刻 15:00:00)"""
    bars_1m = [{"stime": "20250102093100", "close": "100.0"}]
    out = aggregate_bars(bars_1m, "1d")
    assert out[0]["stime"] == "20250102150000"
    assert len(out[0]["stime"]) == 14


# ─────────────── Case 11: unsupported period ───────────────


def test_unsupported_period_raises():
    """unsupported period (e.g. '2m') 抛 ValueError"""
    bars_1m = [{"stime": "20250102093100", "close": "100.0"}]
    with pytest.raises(ValueError, match="unsupported period"):
        aggregate_bars(bars_1m, "2m")
    with pytest.raises(ValueError, match="unsupported period"):
        aggregate_bars(bars_1m, "1w")  # 周线不支持
    with pytest.raises(ValueError, match="unsupported period"):
        aggregate_bars(bars_1m, "")


# ─────────────── Case 12: stime 解析容错 ───────────────


def test_parse_stime_handles_short_8digit():
    """_parse_stime 兼容 8位 YYYYMMDD (历史数据)"""
    dt_obj = _parse_stime("20250102")
    assert dt_obj == dt.datetime(2025, 1, 2, 15, 0, 0)  # 自动补 150000


def test_parse_stime_handles_14digit():
    """_parse_stime 14位 YYYYMMDDHHMMSS 正常解析"""
    dt_obj = _parse_stime("20250102093100")
    assert dt_obj == dt.datetime(2025, 1, 2, 9, 31, 0)


def test_format_stime_intraday():
    """_format_stime intraday 输出 14位"""
    assert _format_stime(dt.datetime(2025, 1, 2, 9, 30), "5m") == "20250102093000"


def test_format_stime_1d():
    """_format_stime 1d 输出 14位 (YYYYMMDD150000)"""
    assert _format_stime(dt.datetime(2025, 1, 2, 0, 0), "1d") == "20250102150000"


# ─────────────── Case 13: 全聚合 large volume ───────────────


def test_aggregate_one_bucket_volume_sum():
    """volume sum 正确 (整数加和)"""
    bars = [
        {"stime": f"2025010209{30+i:02d}00", "close": "100.0", "volume": str(100 * (i+1))}
        for i in range(5)
    ]
    out = aggregate_bars(bars, "5m")
    assert len(out) == 1
    assert out[0]["volume"] == 100 + 200 + 300 + 400 + 500  # 1500


# ─────────────── Case 14: aggregator 端到端 (intraday 实际 broker 风格数据) ───────────────


def test_realistic_broker_1m_data():
    """模拟 broker 1m close 数据 (str 格式, 无 OHLV) → 1d 聚合正确"""
    # broker 实际只返 stime + close, open/high/low/volume 全 0
    bars_1m = [
        {"stime": f"2025010209{30+i//4:02d}{(i%4)*15:02d}00", "close": str(100.0 + i*0.1)}
        for i in range(240)  # A股 1 天 240 根
    ]
    out_1d = aggregate_bars(bars_1m, "1d")
    assert len(out_1d) == 1
    assert out_1d[0]["stime"] == "20250102150000"
    # open/high/low 用 close 兜底 (broker 1m 不返)
    assert out_1d[0]["open"] == 100.0  # 第一根 close
    assert out_1d[0]["close"] == 100.0 + 239*0.1  # 末根 close = 123.9
    assert out_1d[0]["high"] == 123.9
    assert out_1d[0]["low"] == 100.0
    assert out_1d[0]["volume"] == 0  # broker 不返 → 0