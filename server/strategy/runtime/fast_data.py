"""
server/strategy/runtime/fast_data.py — pandas + numpy 加速层 (v10)

目的: 把 list-of-dict bars 转 pandas DataFrame, 让指标计算走向量化路径

设计:
1. bars_to_df(bars) → pd.DataFrame (一次, 后续全部 numpy 操作)
2. IndicatorCache: (field, period) → pd.Series (跨 bar + 跨 combo 共享)
3. sandbox_indicator_dispatch: MA/EMA/REF 等函数检测 ctx['_bars_df'] 存在时走 pandas 路径

加速比: 单 combo 8s → < 1s (期望 8x+), grid 320 combo 43min → < 5min
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import pandas as pd


def bars_to_df(bars: List[Dict[str, Any]]) -> pd.DataFrame:
    """bars (list of dict) → pandas DataFrame (numeric 字段, NaN 容错)

    Returns:
        DataFrame 含 columns: stime / open / high / low / close / volume / amount (按需)
        全部 numeric 字段转 float64, 缺失填 NaN
    """
    if not bars:
        return pd.DataFrame(columns=["stime", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    # 数值字段转换 (broker 可能返 None)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "stime" in df.columns:
        df["stime"] = df["stime"].astype(str)
    return df


class IndicatorCache:
    """指标缓存 (跨 bar + 跨 combo 共享)

    Key 格式: (field, period, kind) → pd.Series
    - MA(period) → 'ma'
    - EMA(period) → 'ema'
    - RSI(period) → 'rsi'
    - BARSLAST → 不缓存

    线程安全 (用 RLock, sandbox 是单线程但 grid 跨 combo 也安全)
    """

    def __init__(self) -> None:
        self._cache: Dict[tuple, pd.Series] = {}
        self._lock = threading.RLock()

    def ma(self, df: pd.DataFrame, period: int, field: str = "close") -> pd.Series:
        """简单移动平均 (整段 bars 一次算)"""
        key = (field, period, "ma")
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and len(cached) == len(df):
                return cached
        # 计算 (在锁外, 避免阻塞)
        s = df[field].rolling(window=period, min_periods=period).mean()
        with self._lock:
            self._cache[key] = s
        return s

    def ema(self, df: pd.DataFrame, period: int, field: str = "close") -> pd.Series:
        """指数移动平均 (整段)"""
        key = (field, period, "ema")
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and len(cached) == len(df):
                return cached
        s = df[field].ewm(span=period, adjust=False, min_periods=period).mean()
        with self._lock:
            self._cache[key] = s
        return s

    def ref(self, df: pd.DataFrame, n: int, field: str = "close") -> pd.Series:
        """REF(bar, n) — 取前 n 根 bar 的字段值 (整段)"""
        key = (field, n, "ref")
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and len(cached) == len(df):
                return cached
        s = df[field].shift(n)
        with self._lock:
            self._cache[key] = s
        return s

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# 模块级单例 (整个 task 共享, 跨 combo 复用)
_task_cache = IndicatorCache()


def get_task_cache() -> IndicatorCache:
    """返当前 task 的 IndicatorCache (默认单例, BacktestEngine 用一个实例隔离)

    用法:
        # 在 BacktestEngine.__init__ 时:
        self.indicator_cache = IndicatorCache()  # 每实例一个 cache
    """
    return _task_cache


__all__ = ["bars_to_df", "IndicatorCache", "get_task_cache"]