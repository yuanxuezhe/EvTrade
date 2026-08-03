"""
test_indicators.py — server/strategy/lib/indicators.py 单元测试

不需要 DB / RPC,纯 stdlib。
"""
import math
import pytest

from server.strategy.lib.indicators import (
    MA, EMA, RSI, MACD, BOLL, KDJ, ATR, BARSLAST, REF, CROSS,
)


# ─────────────── 测试数据生成 ───────────────


def make_bars(prices):
    """给定 close 序列, 自动生成 open/high/low"""
    bars = []
    prev = prices[0]
    for i, c in enumerate(prices):
        c = float(c)
        # 简单合成: open=prev, high/low 围绕 close ±0.5
        o = prev
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        bars.append({
            "stime": f"2026010{i % 9 + 1}0900",
            "open": o, "high": h, "low": l, "close": c, "volume": 1000 + i * 100,
        })
        prev = c
    return bars


@pytest.fixture
def uptrend_bars():
    """10 根单边上行 bar (1.0 -> 1.9, step 0.1)"""
    return make_bars([1.0 + i * 0.1 for i in range(10)])


@pytest.fixture
def oscillation_bars():
    """20 根来回震荡 bar"""
    prices = [1.0 + 0.1 * ((-1) ** i * (i % 4) + 2) for i in range(20)]
    return make_bars(prices)


# ─────────────── MA ───────────────


class TestMA:
    def test_basic(self, uptrend_bars):
        # MA(5) of [1.6, 1.7, 1.8, 1.9] = avg of last 5 closes [1.5..1.9]
        result = MA(uptrend_bars, 5)
        assert result == pytest.approx(1.7, abs=0.001)

    def test_insufficient_data(self, uptrend_bars):
        assert MA(uptrend_bars, 11) is None  # 只有 10 根

    def test_zero_period(self, uptrend_bars):
        with pytest.raises(ValueError):
            MA(uptrend_bars, 0)


# ─────────────── EMA ───────────────


class TestEMA:
    def test_basic(self, uptrend_bars):
        result = EMA(uptrend_bars, 5)
        # EMA 值域 (0.3..1.0) 大致
        assert result is not None
        assert 1.5 < result < 2.0

    def test_first_value(self, uptrend_bars):
        # EMA(period=10) with 10 bars 应不抛错
        assert EMA(uptrend_bars, 10) is not None


# ─────────────── RSI ───────────────


class TestRSI:
    def test_perfect_uptrend(self, uptrend_bars):
        # 单边上行 → RSI 接近 100
        result = RSI(uptrend_bars, 5)
        assert result is not None
        assert result > 95

    def test_insufficient_data(self):
        bars = make_bars([1.0] * 10)
        assert RSI(bars, 14) is None

    def test_perfect_downtrend(self):
        bars = make_bars([2.0 - i * 0.1 for i in range(20)])
        result = RSI(bars, 14)
        assert result is not None
        assert result < 5


# ─────────────── MACD ───────────────


class TestMACD:
    def test_basic(self, uptrend_bars):
        # MACD 默认 12/26/9 需要 26+9=35 根, 用大段数据
        bars = make_bars([1.0 + i * 0.05 for i in range(50)])
        result = MACD(bars, 8, 17, 5)  # 22 根够
        # 单边上涨, DIF > 0, BAR > 0
        assert result is not None
        dif, dea, bar = result
        assert dif > 0
        assert bar > 0

    def test_insufficient_data(self):
        bars = make_bars([1.0 + i for i in range(20)])
        # 默认 12/26/9 需要 35 根
        assert MACD(bars, 12, 26, 9) is None

    def test_invalid_params(self):
        bars = make_bars([1.0 + i for i in range(50)])
        with pytest.raises(ValueError):
            MACD(bars, 26, 12, 9)  # fast >= slow


# ─────────────── BOLL ───────────────


class TestBOLL:
    def test_basic(self, oscillation_bars):
        result = BOLL(oscillation_bars, 10, 2.0)
        assert result is not None
        mid, upper, lower = result
        assert lower < mid < upper
        assert (upper - mid) == pytest.approx(mid - lower, abs=0.001)

    def test_insufficient(self, uptrend_bars):
        assert BOLL(uptrend_bars, 11) is None


# ─────────────── KDJ ───────────────


class TestKDJ:
    def test_basic(self, oscillation_bars):
        result = KDJ(oscillation_bars, 9, 3, 3)
        assert result is not None
        K, D, J = result
        assert -50 <= K <= 150  # K 通常 0-100
        assert -50 <= D <= 150
        # J = 3K - 2D
        assert J == pytest.approx(3 * K - 2 * D, abs=0.001)


# ─────────────── ATR ───────────────


class TestATR:
    def test_basic(self, uptrend_bars):
        result = ATR(uptrend_bars, 5)
        assert result is not None
        assert result > 0


# ─────────────── BARSLAST ───────────────


class TestBARSLAST:
    def test_current(self, uptrend_bars):
        # 当前 bar 的 close > 1.8 时, BARSLAST = 0
        result = BARSLAST(uptrend_bars, lambda b, i: b["close"] > 1.8)
        assert result == 0

    def test_n_bars_ago(self, uptrend_bars):
        # uptrend_bars close = [1.0..1.9] (idx 0..9)
        # close > 1.4 条件最后一次满足是 idx=9 (close=1.9)
        # 距今 = len(10) - 1 - 9 = 0
        result = BARSLAST(uptrend_bars, lambda b, i: b["close"] > 1.4)
        assert result == 0

    def test_specific_n(self):
        # 10 根 close = [1.0..1.9], 条件 = close == 1.5
        # idx=5 是最后一次 (1.5 之后还有 >1.5 不再满足)
        # 距今 = 10-1-5 = 4
        bars = make_bars([1.0 + i * 0.1 for i in range(10)])
        result = BARSLAST(bars, lambda b, i: b["close"] == 1.5)
        assert result == 4

    def test_never(self):
        bars = make_bars([1.0] * 5)
        result = BARSLAST(bars, lambda b, i: b["close"] > 999.0)
        assert result == 999


# ─────────────── REF ───────────────


class TestREF:
    def test_n0(self, uptrend_bars):
        # n=0 = 当前
        assert REF(uptrend_bars, 0) == pytest.approx(1.9, abs=0.001)

    def test_n1(self, uptrend_bars):
        # n=1 = 上一根
        assert REF(uptrend_bars, 1) == pytest.approx(1.8, abs=0.001)

    def test_n_too_large(self, uptrend_bars):
        assert REF(uptrend_bars, 100) is None


# ─────────────── CROSS ───────────────


class TestCROSS:
    def test_cross_up(self):
        assert CROSS(2.0, 1.0, prev_a=0.9, prev_b=1.5) is True

    def test_no_cross(self):
        assert CROSS(1.0, 1.5, prev_a=1.2, prev_b=1.5) is False  # A 仍 < B

    def test_already_above(self):
        # 今日 a>b, 但昨日 a 也 > b → 不算上穿
        assert CROSS(2.0, 1.0, prev_a=1.5, prev_b=1.0) is False

    def test_none(self):
        assert CROSS(None, 1.0, 1.0, 1.0) is False
        assert CROSS(1.0, None, 1.0, 1.0) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])