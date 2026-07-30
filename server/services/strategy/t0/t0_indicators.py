"""
strategy/t0/t0_indicators.py — T0 专用指标计算（纯函数，无副作用）

📌 VWAP（成交量加权平均价）
📌 布林线（Bollinger Bands）
📌 K 线形态识别（下影线、止跌阳线、量能不足）

纯 stdlib，无 numpy/pandas。所有函数返 Optional，数据不足时返 None。
"""
import math
from typing import List, Optional, Sequence, Tuple

from server.services.strategy.t0.bar_aggregator import Bar
from server.services.strategy.indicators import _rsi_wilder


# ─────────────── VWAP ───────────────

def compute_vwap(ticks: List[dict]) -> Optional[float]:
    """VWAP = Σ(price × volume) / Σ(volume)

    自开盘以来全部 tick。至少需要一个 volume > 0 的 tick。
    tick 格式: {"last_price": float, "volume": int}
    """
    total_pv = 0.0
    total_v = 0
    for t in ticks:
        p = t.get("last_price")
        v = t.get("volume")
        if p is not None and v and v > 0:
            total_pv += float(p) * int(v)
            total_v += int(v)
    if total_v <= 0:
        return None
    return total_pv / total_v


def compute_vwap_incremental(prev_vwap: Optional[float],
                              prev_pv: float, prev_v: int,
                              price: float, volume: int) -> Tuple[Optional[float], float, int]:
    """增量 VWAP 计算（避免每次遍历全天 tick）。

    返回 (vwap, cumulative_pv, cumulative_volume)。
    caller 维护 prev_pv 和 prev_v 状态。
    """
    if volume <= 0:
        return (prev_vwap, prev_pv, prev_v)
    pv = float(price) * volume
    cv = prev_v + volume
    cpv = prev_pv + pv
    if cv <= 0:
        return (None, cpv, cv)
    return (cpv / cv, cpv, cv)


def compute_vwap_deviation(price: float, vwap: float) -> float:
    """股价相对 VWAP 的偏离度: (price - vwap) / vwap

    正值 = 在 VWAP 上方，负值 = 在 VWAP 下方。
    vwap <= 0 时返 0.0。
    """
    if vwap <= 0:
        return 0.0
    return (price - vwap) / vwap


# ─────────────── 布林线 ───────────────

def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: Sequence[float]) -> float:
    """总体标准差"""
    n = len(values)
    if n < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / n
    return math.sqrt(variance)


def compute_bollinger_bands(
    prices: Sequence[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> Optional[Tuple[float, float, float]]:
    """布林线 (upper, middle, lower)。

    middle = SMA(prices[-period:], period)
    upper/lower = middle ± std_mult × stdev(prices[-period:])
    len(prices) < period → None
    """
    if len(prices) < period or period <= 0:
        return None
    window = list(prices)[-period:]
    middle = _mean(window)
    std = _stdev(window)
    return (middle + std_mult * std, middle, middle - std_mult * std)


# ─────────────── K 线形态识别 ───────────────

def detect_lower_shadow(bar: Bar, threshold: float = 0.3) -> bool:
    """下影线是否显著（下影线长度 / 实体长度 > threshold）。

    下影线 = min(open, close) - low
    实体 = abs(close - open)
    实体为 0 时（十字星），下影线 > 0 即视为显著。
    """
    body = abs(bar.close - bar.open)
    lower_shadow = min(bar.open, bar.close) - bar.low
    if body <= 0:
        return lower_shadow > 0
    return (lower_shadow / body) >= threshold


def detect_zhiting_yangxian(bar: Bar) -> bool:
    """止跌阳线: close > open 且 close 位于上半区

    close > open（阳线）且 close > (high + low) / 2（收在上半区）
    """
    if bar.close <= bar.open:
        return False
    mid = (bar.high + bar.low) / 2
    return bar.close > mid


def detect_insufficient_volume(current_bar: Bar,
                                prev_bars: List[Bar],
                                threshold: float = 0.6,
                                lookback: int = 5) -> bool:
    """量能不足: 当前 bar 成交量 < 前 N 根均值的 threshold 倍。

    用于卖出信号确认（股价拉升但量能跟不上）。
    prev_bars 不足 lookback 根 → 不判断（返 False）。
    """
    if len(prev_bars) < lookback or lookback <= 0:
        return False
    avg_vol = sum(b.volume for b in prev_bars[-lookback:]) / lookback
    if avg_vol <= 0:
        return False
    return current_bar.volume < avg_vol * threshold


# ─────────────── 量能趋势判断 ───────────────

def classify_volume_trend(current_bar: Bar,
                          prev_bars: List[Bar],
                          increase_threshold: float = 1.5,
                          panic_threshold: float = 3.0,
                          lookback: int = 3) -> str:
    """分类量能趋势: 'increasing' / 'panic' / 'normal' / 'decreasing'

    increasing: 当前 vol > 前 N 根均值 × increase_threshold
    panic: 当前 vol > 前 N 根均值 × panic_threshold
    decreasing: 当前 vol < 前 N 根均值 × 0.5
    normal: 其他
    """
    if len(prev_bars) < lookback or lookback <= 0 or current_bar.volume <= 0:
        return "normal"
    avg_vol = sum(b.volume for b in prev_bars[-lookback:]) / lookback
    if avg_vol <= 0:
        return "normal"
    ratio = current_bar.volume / avg_vol
    if ratio >= panic_threshold:
        return "panic"
    if ratio >= increase_threshold:
        return "increasing"
    if ratio < 0.5:
        return "decreasing"
    return "normal"


__all__ = [
    "compute_vwap", "compute_vwap_incremental", "compute_vwap_deviation",
    "compute_bollinger_bands",
    "detect_lower_shadow", "detect_zhiting_yangxian", "detect_insufficient_volume",
    "classify_volume_trend",
]
