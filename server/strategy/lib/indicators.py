"""
server/strategy/lib/indicators.py — 纯函数指标层

📌 设计：
- 所有指标接 bars (list[dict]) + 参数, 返 float | None 或 tuple[float, ...] | None
- bars 长度不足或字段缺失 → 返 None (不抛异常, 调用方按 None 判断)
- 不依赖 numpy / pandas (server/requirements.txt 不含)
- bar 格式: {"stime": "...", "open": float, "high": float, "low": float, "close": float, "volume": int}

📌 命名遵循通达信 / 同花顺习惯:
- MA(N)        简单移动平均
- EMA(N)       指数移动平均
- RSI(N)       相对强弱
- MACD         12/26/9 标准
- BOLL(N,P)    布林带 (中轨/上轨/下轨)
- KDJ          9/3/3 随机指标
- ATR(N)       平均真实波幅
- BARSLAST     自定义条件首次成立距今 bar 数
- REF(N)       N bar 前的收盘价
- CROSS(A,B)   A 上穿 B (昨日 A<=B, 今日 A>B)
"""
from __future__ import annotations

from typing import List, Dict, Optional, Tuple, Any, Callable


# ─────────────── 内部辅助 ───────────────


def _closes(bars: List[Dict[str, Any]], field: str = "close") -> List[float]:
    """提取 close 序列 (None 跳过)"""
    out: List[float] = []
    for b in bars:
        v = b.get(field)
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _bar(bars: List[Dict[str, Any]], idx: int, field: str) -> Optional[float]:
    """取第 idx 根 bar 的字段值 (负数 = 从尾部倒数; None / OOB → None)"""
    if not bars:
        return None
    real_idx = idx if idx >= 0 else len(bars) + idx
    if real_idx < 0 or real_idx >= len(bars):
        return None
    v = bars[real_idx].get(field)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─────────────── MA ───────────────


def MA(bars: List[Dict[str, Any]], period: int, field: str = "close") -> Optional[float]:
    """简单移动平均 (最新一根 bar 收盘的 MA 值)

    Args:
        bars: K 线序列
        period: 周期
        field: 参与计算的字段名, 默认 'close'

    Returns:
        None 当 bars 长度 < period 或字段缺失
    """
    if period <= 0:
        raise ValueError(f"MA: period must be positive, got {period}")
    closes = _closes(bars, field)
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


# ─────────────── EMA ───────────────


class _EMAState:
    """EMA 计算器 (alpha = 2/(N+1), 第一个值种子 = 首根 close)"""

    __slots__ = ("alpha", "value", "seeded")

    def __init__(self, period: int) -> None:
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.seeded = False

    def update(self, x: float) -> float:
        if not self.seeded:
            self.value = x
            self.seeded = True
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


def EMA(bars: List[Dict[str, Any]], period: int, field: str = "close") -> Optional[float]:
    """指数移动平均 (最新一根 bar 的 EMA 值)

    至少需要 1 根 bar;首根时返其值本身。
    """
    if period <= 0:
        raise ValueError(f"EMA: period must be positive, got {period}")
    closes = _closes(bars, field)
    if not closes:
        return None
    ema = _EMAState(period)
    for c in closes:
        ema.update(c)
    return ema.value


# ─────────────── RSI ───────────────


def RSI(bars: List[Dict[str, Any]], period: int = 14, field: str = "close") -> Optional[float]:
    """Wilder 平滑 RSI (最新一根 bar 的 RSI 值)

    Args:
        period: Wilder 周期, 默认 14
    Returns:
        0-100, None 当 bars 长度不足 (需要 >= period+1 根才能产生第一组 avg gain/loss)
    """
    if period <= 0:
        raise ValueError(f"RSI: period must be positive, got {period}")
    closes = _closes(bars, field)
    if len(closes) < period + 1:
        return None

    # 前 period 个 close 的 delta 取平均作为初始 avg
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas[:period]]
    losses = [-min(d, 0.0) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder 平滑: 后续 delta
    for d in deltas[period:]:
        gain = max(d, 0.0)
        loss = -min(d, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ─────────────── MACD ───────────────


def MACD(
    bars: List[Dict[str, Any]],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    field: str = "close",
) -> Optional[Tuple[float, float, float]]:
    """MACD 指标 (DIF, DEA, BAR) — 12/26/9 标准配置

    Returns:
        (dif, dea, bar) tuple, None 当 bars 长度不足 (< slow + signal)
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD: fast/slow/signal must be positive")
    if fast >= slow:
        raise ValueError(f"MACD: fast ({fast}) must be < slow ({slow})")
    closes = _closes(bars, field)
    if len(closes) < slow + signal:
        return None

    ema_fast = _EMAState(fast)
    ema_slow = _EMAState(slow)
    difs: List[float] = []
    for c in closes:
        ema_fast.update(c)
        ema_slow.update(c)
        difs.append(ema_fast.value - ema_slow.value)

    ema_signal = _EMAState(signal)
    for d in difs:
        ema_signal.update(d)

    dif = difs[-1]
    dea = ema_signal.value
    bar = (dif - dea) * 2.0
    return dif, dea, bar


# ─────────────── BOLL ───────────────


def BOLL(
    bars: List[Dict[str, Any]],
    period: int = 20,
    stddev: float = 2.0,
    field: str = "close",
) -> Optional[Tuple[float, float, float]]:
    """布林带 (中轨, 上轨, 下轨)

    Returns:
        (mid, upper, lower), None 当 bars 长度 < period
    """
    if period <= 0:
        raise ValueError(f"BOLL: period must be positive, got {period}")
    closes = _closes(bars, field)
    if len(closes) < period:
        return None

    window = closes[-period:]
    mean = sum(window) / period
    # 总体标准差 (除以 N, 与通达信默认一致)
    var = sum((x - mean) ** 2 for x in window) / period
    std = var ** 0.5
    mid = mean
    upper = mean + stddev * std
    lower = mean - stddev * std
    return mid, upper, lower


# ─────────────── KDJ ───────────────


def KDJ(
    bars: List[Dict[str, Any]],
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> Optional[Tuple[float, float, float]]:
    """KDJ 随机指标 (K, D, J)

    计算口径 (通达信):
      RSV(n) = (C - LLV(L, n)) / (HHV(H, n) - LLV(L, n)) * 100  (n=0 时 RSV=50 兜底)
      K = SMA(RSV, m1, 1)  ← 平滑系数 1/(m1)
      D = SMA(K,   m2, 1)
      J = 3K - 2D

    Returns:
        (K, D, J), None 当 bars 长度不足 (< n)
    """
    if n <= 0 or m1 <= 0 or m2 <= 0:
        raise ValueError("KDJ: n/m1/m2 must be positive")
    if len(bars) < n:
        return None

    # 计算每根 bar 的 RSV
    rsvs: List[float] = []
    for i in range(len(bars)):
        start = max(0, i - n + 1)
        window = bars[start:i + 1]
        highs = [b["high"] for b in window if b.get("high") is not None]
        lows = [b["low"] for b in window if b.get("low") is not None]
        closes = [b["close"] for b in window if b.get("close") is not None]
        if not highs or not lows or not closes:
            rsvs.append(50.0)  # 兜底
            continue
        hh = max(highs)
        ll = min(lows)
        c = closes[-1]
        if hh == ll:
            rsvs.append(50.0)
        else:
            rsvs.append((c - ll) / (hh - ll) * 100.0)

    # SMA(RSV, m1, 1): 系数 = 1/m1
    k_vals: List[float] = []
    sma_k = _SMAState(1.0 / m1)
    for r in rsvs:
        sma_k.update(r)
        k_vals.append(sma_k.value)

    sma_d = _SMAState(1.0 / m2)
    d_vals: List[float] = []
    for k in k_vals:
        sma_d.update(k)
        d_vals.append(sma_d.value)

    K = k_vals[-1]
    D = d_vals[-1]
    J = 3 * K - 2 * D
    return K, D, J


class _SMAState:
    """通达信式 SMA(X, N, M): Y = (M*X + (N-M)*Y') / N"""

    __slots__ = ("alpha", "value", "seeded")

    def __init__(self, alpha: float) -> None:
        self.alpha = alpha
        self.value = 0.0
        self.seeded = False

    def update(self, x: float) -> float:
        if not self.seeded:
            self.value = x
            self.seeded = True
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


# ─────────────── ATR ───────────────


def ATR(bars: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    """SMA ATR (最新一根 bar 的 ATR 值)

    Returns:
        None 当 bars 长度 < 2 (需要一根 prev close 算 TR)
        实际可用需要 period+1 根以获得稳定均值
    """
    if period <= 0:
        raise ValueError(f"ATR: period must be positive, got {period}")
    if len(bars) < 2:
        return None

    trs: List[float] = []
    prev_c: Optional[float] = None
    for b in bars:
        h, l, c = b.get("high"), b.get("low"), b.get("close")
        if h is None or l is None or c is None:
            prev_c = c if c is not None else prev_c
            continue
        h = float(h); l = float(l); c = float(c)
        if prev_c is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
        prev_c = c

    if len(trs) < 1:
        return None
    # 取最后 period 个 TR 的 SMA
    window = trs[-period:]
    return sum(window) / len(window)


# ─────────────── BARSLAST ───────────────


def BARSLAST(bars: List[Dict[str, Any]], cond: Callable[[Dict[str, Any], int], bool]) -> int:
    """距上次 cond(bar, idx) 为 True 的 bar 数 (含当前 bar 时也计数)

    Args:
        bars: K 线序列
        cond: 函数 (bar_dict, idx) -> bool, idx 0..len(bars)-1 (0=最早一根)

    Returns:
        0 表示当前 bar 满足, 正整数表示距上次满足的 bar 数
        999 表示从未满足过 (用一个大数代替, 避免策略脚本到处判 None)
    """
    NEVER = 999
    last_idx: Optional[int] = None
    for i, b in enumerate(bars):
        if cond(b, i):
            last_idx = i
    if last_idx is None:
        return NEVER
    return len(bars) - 1 - last_idx


# ─────────────── REF ───────────────


def REF(bars: List[Dict[str, Any]], n: int, field: str = "close") -> Optional[float]:
    """N bar 前的字段值 (n=0 = 当前 bar, n=1 = 上一根 bar)

    Returns:
        None 当 n >= len(bars) 或字段缺失
    """
    if n < 0:
        raise ValueError(f"REF: n must be non-negative, got {n}")
    return _bar(bars, -1 - n, field)


# ─────────────── CROSS ───────────────


def CROSS(a: Optional[float], b: Optional[float], prev_a: Optional[float], prev_b: Optional[float]) -> bool:
    """A 上穿 B (今日 a>b, 昨日 a<=b)

    Args:
        a: 今日 A 值
        b: 今日 B 值
        prev_a: 昨日 A 值
        prev_b: 昨日 B 值

    Returns:
        True 当 a,b,prev_a,prev_b 都不为 None 且满足"昨 a<=昨 b 今 a>b"
    """
    if a is None or b is None or prev_a is None or prev_b is None:
        return False
    return prev_a <= prev_b and a > b


__all__ = [
    "MA", "EMA", "RSI", "MACD", "BOLL", "KDJ", "ATR",
    "BARSLAST", "REF", "CROSS",
]