"""
test_indicators.py — 纯函数指标层单测（task 3）

覆盖：
- TickBuffer：append / last / last_n / prices / volumes / 100 上限 FIFO
- IndicatorParams：frozen + 3 preset（standard / short_term / long_term）
- compute_ma：已知序列 + 不足返 None + NaN 返 None
- compute_rsi：单调上涨 → 100；自定义 period 生效
- compute_macd：自定义 params 生效 + bar 不变量 + 不足返 None
- compute_vol_avg：已知序列 + 不足返 None + NaN 返 None
"""
import math
import pytest


# ─────────────── TickBuffer ───────────────


def test_buffer_append_and_last_n():
    from server.services.strategy.indicators import TickBuffer
    b = TickBuffer()
    for i in range(5):
        b.append({"last_price": float(i), "volume": i * 100})
    assert len(b) == 5
    assert b.last() == {"last_price": 4.0, "volume": 400}
    n3 = b.last_n(3)
    assert [t["last_price"] for t in n3] == [2.0, 3.0, 4.0]


def test_buffer_fifo_eviction_at_capacity():
    from server.services.strategy.indicators import TickBuffer
    b = TickBuffer(max_size=10)
    for i in range(15):
        b.append({"last_price": float(i)})
    assert len(b) == 10
    # 最旧的 0..4 已被弹出，剩 5..14
    assert [t["last_price"] for t in b.last_n(10)] == [float(x) for x in range(5, 15)]
    assert b.last()["last_price"] == 14.0


def test_buffer_underflow_returns_partial():
    from server.services.strategy.indicators import TickBuffer
    b = TickBuffer()
    b.append({"last_price": 1.0})
    # last_n 超容量返全部
    assert b.last_n(5) == [{"last_price": 1.0}]
    # last 空 buffer 返 None
    empty = TickBuffer()
    assert empty.last() is None
    assert empty.last_n(3) == []


def test_buffer_prices_and_volumes_skip_missing_fields():
    from server.services.strategy.indicators import TickBuffer
    b = TickBuffer()
    b.append({"last_price": 10.0, "volume": 100})
    b.append({"last_price": 11.0})  # 无 volume
    b.append({"volume": 300})  # 无 last_price
    assert b.prices() == [10.0, 11.0]
    assert b.volumes() == [100, 300]


# ─────────────── IndicatorParams ───────────────


def test_indicator_params_default_is_standard():
    from server.services.strategy.indicators import IndicatorParams
    p = IndicatorParams()
    assert p.ma_periods == (5, 10, 20)
    assert p.rsi_period == 6
    assert (p.macd_fast, p.macd_slow, p.macd_dea) == (12, 26, 9)
    assert IndicatorParams.standard() == p


def test_indicator_params_presets():
    from server.services.strategy.indicators import IndicatorParams
    short = IndicatorParams.short_term()
    assert short.macd_fast == 6 and short.macd_slow == 13 and short.macd_dea == 5
    assert short.ma_periods == (3, 6, 10)

    long = IndicatorParams.long_term()
    assert long.rsi_period == 14
    assert long.ma_periods == (10, 20, 60)
    assert long.vol_period == 30


def test_indicator_params_frozen_immutable():
    from server.services.strategy.indicators import IndicatorParams
    p = IndicatorParams()
    with pytest.raises(Exception):  # FrozenInstanceError
        p.macd_fast = 5  # type: ignore


def test_indicator_params_macd_min_ticks():
    from server.services.strategy.indicators import IndicatorParams
    assert IndicatorParams.standard().macd_min_ticks() == 26 + 9 - 1  # 34
    assert IndicatorParams.short_term().macd_min_ticks() == 13 + 5 - 1  # 17


# ─────────────── compute_ma ───────────────


def test_ma_known_sequence():
    from server.services.strategy.indicators import compute_ma
    # MA(3) of [1,2,3,4,5] = (3+4+5)/3 = 4.0
    assert compute_ma([1, 2, 3, 4, 5], 3) == 4.0
    # MA(5) of same = 3.0
    assert compute_ma([1, 2, 3, 4, 5], 5) == 3.0


def test_ma_insufficient_returns_none():
    from server.services.strategy.indicators import compute_ma
    assert compute_ma([1.0, 2.0], 5) is None
    assert compute_ma([], 5) is None


def test_ma_nan_returns_none():
    from server.services.strategy.indicators import compute_ma
    assert compute_ma([1.0, 2.0, float("nan"), 4.0, 5.0], 3) is None


# ─────────────── compute_rsi ───────────────


def test_rsi_monotonic_rise_returns_100():
    from server.services.strategy.indicators import compute_rsi
    # 7 根单调上涨 → avg_loss=0 → RSI=100
    prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    assert compute_rsi(prices, period=6) == 100.0


def test_rsi_monotonic_fall_returns_zero():
    from server.services.strategy.indicators import compute_rsi
    # 7 根单调下跌 → avg_gain=0 → RSI=0
    prices = [16.0, 15.0, 14.0, 13.0, 12.0, 11.0, 10.0]
    assert compute_rsi(prices, period=6) == 0.0


def test_rsi_custom_period():
    from server.services.strategy.indicators import compute_rsi
    # period=3 也能跑
    prices = [10.0, 11.0, 12.0, 13.0]
    val = compute_rsi(prices, period=3)
    assert val is not None
    assert 80 < val <= 100  # 接近全涨


def test_rsi_insufficient_returns_none():
    from server.services.strategy.indicators import compute_rsi
    # period=6 需要至少 7 根
    assert compute_rsi([1.0, 2.0, 3.0], 6) is None


def test_rsi_nan_returns_none():
    from server.services.strategy.indicators import compute_rsi
    prices = [1.0, 2.0, float("nan"), 4.0, 5.0, 6.0, 7.0]
    assert compute_rsi(prices, period=6) is None


# ─────────────── compute_macd ───────────────


def test_macd_returns_tuple_and_bar_invariant():
    from server.services.strategy.indicators import compute_macd, IndicatorParams
    # 构造 60 根温和上涨序列
    prices = [10.0 + 0.1 * i for i in range(60)]
    result = compute_macd(prices, IndicatorParams.standard())
    assert result is not None
    dif, dea, bar = result
    assert bar == pytest.approx((dif - dea) * 2.0)
    # DIF/DEA 是 float
    assert isinstance(dif, float) and isinstance(dea, float) and isinstance(bar, float)


def test_macd_with_custom_params():
    from server.services.strategy.indicators import compute_macd, IndicatorParams
    # 短周期 6/13/5 只需要 17+ 根
    prices = [10.0 + 0.1 * i for i in range(25)]
    result = compute_macd(prices, IndicatorParams.short_term())
    assert result is not None
    dif, dea, bar = result
    assert math.isfinite(dif) and math.isfinite(dea) and math.isfinite(bar)


def test_macd_insufficient_returns_none():
    from server.services.strategy.indicators import compute_macd, IndicatorParams
    # standard 需要 34 根
    assert compute_macd([10.0 + i for i in range(30)], IndicatorParams.standard()) is None
    # short_term 需要 17 根
    assert compute_macd([10.0 + i for i in range(15)], IndicatorParams.short_term()) is None


def test_macd_nan_returns_none():
    from server.services.strategy.indicators import compute_macd, IndicatorParams
    prices = [10.0 + 0.1 * i for i in range(40)]
    prices[20] = float("nan")
    assert compute_macd(prices, IndicatorParams.standard()) is None


# ─────────────── compute_vol_avg ───────────────


def test_vol_avg_known_sequence():
    from server.services.strategy.indicators import compute_vol_avg
    # MA(3) of [100, 200, 300, 400] = (200+300+400)/3 = 300
    assert compute_vol_avg([100, 200, 300, 400], 3) == 300.0


def test_vol_avg_insufficient_returns_none():
    from server.services.strategy.indicators import compute_vol_avg
    assert compute_vol_avg([100, 200], 20) is None
    assert compute_vol_avg([], 20) is None


def test_vol_avg_nan_returns_none():
    from server.services.strategy.indicators import compute_vol_avg
    vols = [100, 200, float("nan"), 400, 500] + [100] * 20
    assert compute_vol_avg(vols, 5) is None


# ─────────────── Smoke ───────────────


def test_smoke_imports():
    from server.services.strategy.indicators import (
        TickBuffer, IndicatorParams,
        compute_ma, compute_rsi, compute_macd, compute_vol_avg,
    )
    assert TickBuffer is not None
    assert IndicatorParams.standard().macd_fast == 12