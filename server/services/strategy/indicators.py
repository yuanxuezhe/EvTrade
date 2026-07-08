"""
strategy — 纯函数指标层（change strategy_trade task 3）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-002
📌 4 类指标：MA / RSI / MACD / VolAvg
📌 9 种 flag 派生（ma_bullish/bearish, rsi_over/under, vol_breakout, price_change_up/down, macd_golden/death_cross）

设计要点：
- 所有指标函数返 Optional[float]，**buffer 不足或含 NaN 时返 None**（flags 不触发）
- 指标参数 **不写死**，通过 `IndicatorParams` frozen dataclass 传入
  - v1 手动配置（前端 StrategyConfig 录入）
  - 后续接入"市场状态识别"模块自动切换 preset（standard / short_term / ...）
- 纯 stdlib（无 numpy / pandas，server/requirements.txt 不含）
- Python 3.6.8 兼容：Optional[T] / Tuple[T, T, T] typing，不用 | / dict[] PEP 604/585 语法
"""
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple, List, Sequence
import math


# ─────────────── 参数集（frozen dataclass） ───────────────


@dataclass(frozen=True)
class IndicatorParams:
    """指标参数集（v1 手动配置，后续由市场状态识别模块自动切换）。

    📌 frozen=True 防止运行期被篡改；切换 preset 时整体替换对象
    📌 字段说明：
       - ma_periods: MA 计算周期列表（默认 [5,10,20]，对应 flag ma_bullish/bearish 需同时满足 MA5>MA10>MA20）
       - rsi_period: RSI Wilder 平滑周期（默认 6，T0 短线偏好）
       - macd_fast/slow/dea: MACD 三周期（默认 12/26/9 标准；短周期可切 6/13/5）
       - vol_period: 量能 MA 周期（默认 20，vol_breakout 用 vol ≥ 2×MA_VOL）
    """
    ma_periods: Tuple[int, ...] = (5, 10, 20)
    rsi_period: int = 6
    macd_fast: int = 12
    macd_slow: int = 26
    macd_dea: int = 9
    vol_period: int = 20

    @classmethod
    def standard(cls) -> "IndicatorParams":
        """标准 preset：12/26/9 MACD + 5/10/20 MA + RSI(6)（默认）"""
        return cls()  # dataclass default == standard

    @classmethod
    def short_term(cls) -> "IndicatorParams":
        """T0 短线 preset：6/13/5 MACD + 3/6/10 MA + RSI(6)"""
        return cls(
            ma_periods=(3, 6, 10),
            macd_fast=6, macd_slow=13, macd_dea=5,
        )

    @classmethod
    def long_term(cls) -> "IndicatorParams":
        """趋势长线 preset：19/39/9 MACD + 10/20/60 MA + RSI(14)"""
        return cls(
            ma_periods=(10, 20, 60),
            rsi_period=14,
            macd_fast=19, macd_slow=39, macd_dea=9,
            vol_period=30,
        )

    def macd_min_ticks(self) -> int:
        """MACD 计算最少需要的 tick 数 = slow + dea - 1（EMA 收敛周期）"""
        return self.macd_slow + self.macd_dea - 1


# ─────────────── TickBuffer ───────────────


class TickBuffer:
    """滚动 100-tick 环形缓冲（hqserver 原始 tick dict 序列）。

    📌 内部用 collections.deque(maxlen=100) 保证 FIFO + 固定内存
    📌 append / last_n / last / __len__ 四个 API
    📌 指标层只读 last_price / volume 字段，不修改 tick dict
    """
    MAX_SIZE = 100

    def __init__(self, max_size: int = MAX_SIZE):
        self._buf = deque(maxlen=max_size)

    def append(self, tick: dict) -> None:
        """追加一帧 tick；超 max_size 自动弹出最旧"""
        self._buf.append(tick)

    def last(self) -> Optional[dict]:
        """最新一帧（None 当 buffer 空）"""
        return self._buf[-1] if self._buf else None

    def last_n(self, n: int) -> List[dict]:
        """最近 n 帧（按时间正序：旧→新），n > len(buf) 时返全部"""
        if n <= 0 or not self._buf:
            return []
        n = min(n, len(self._buf))
        return list(self._buf)[-n:]

    def prices(self, n: Optional[int] = None) -> List[float]:
        """最近 n 帧的 last_price 列表（None 当字段缺失；buffer 不足返全部）"""
        frames = self.last_n(n) if n is not None else list(self._buf)
        out = []
        for t in frames:
            p = t.get("last_price")
            if p is None:
                continue
            out.append(float(p))
        return out

    def volumes(self, n: Optional[int] = None) -> List[int]:
        """最近 n 帧的 volume 列表"""
        frames = self.last_n(n) if n is not None else list(self._buf)
        out = []
        for t in frames:
            v = t.get("volume")
            if v is None:
                continue
            out.append(int(v))
        return out

    def __len__(self) -> int:
        return len(self._buf)


# ─────────────── 私有 helper（pure stdlib，无 numpy） ───────────────


def _has_nan(seq: Sequence[float]) -> bool:
    """序列中是否含 NaN / inf"""
    for x in seq:
        try:
            if math.isnan(x) or math.isinf(x):
                return True
        except TypeError:
            return True
    return False


def _sma(prices: Sequence[float], period: int) -> Optional[float]:
    """简单移动平均；prices 长度 < period 返 None"""
    if period <= 0 or len(prices) < period:
        return None
    if _has_nan(prices):
        return None
    return sum(prices[-period:]) / period


def _ema(series: Sequence[float], period: int) -> Optional[float]:
    """标准指数移动平均 α = 2 / (period + 1)；series 长度 < period 返 None

    📌 用递归式：EMA_today = α * price_today + (1 - α) * EMA_yesterday
    📌 初值用前 period 项的 SMA 作 seed（业界常见做法，避免依赖外部传入 prev_ema）
    """
    if period <= 0 or len(series) < period:
        return None
    if _has_nan(series):
        return None
    alpha = 2.0 / (period + 1.0)
    ema = sum(series[:period]) / period  # SMA seed
    for x in series[period:]:
        ema = alpha * x + (1 - alpha) * ema
    return ema


def _rsi_wilder(prices: Sequence[float], period: int) -> Optional[float]:
    """Wilder 平滑 RSI（α = 1/period）；prices 长度 < period + 1 返 None

    📌 Wilder 算法（区别于标准 EMA RSI）：
       - 前 period 根算初始 avg_gain / avg_loss（简单均值）
       - 后续：avg_gain = (prev_avg_gain * (period-1) + gain) / period
       - RS = avg_gain / avg_loss；RSI = 100 - 100/(1+RS)
    📌 全部上涨 → RSI=100；全部下跌 → RSI=0；avg_loss=0 且 avg_gain=0 → RSI=50（中性防御）
    """
    if period <= 0 or len(prices) < period + 1:
        return None
    if _has_nan(prices):
        return None
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    # 初值：前 period 项均值
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # 后续 Wilder 平滑
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


# ─────────────── 公共指标函数 ───────────────


def compute_ma(prices: Sequence[float], period: int) -> Optional[float]:
    """简单移动平均 MA；buffer 不足或 NaN 返 None"""
    return _sma(prices, period)


def compute_rsi(prices: Sequence[float], period: int = 6) -> Optional[float]:
    """Wilder RSI 0-100；buffer 不足或 NaN 返 None"""
    return _rsi_wilder(prices, period)


def compute_macd(
    prices: Sequence[float], params: IndicatorParams = None
) -> Optional[Tuple[float, float, float]]:
    """MACD 三元组 (dif, dea, bar)；bar = (dif - dea) * 2

    📌 DIF = EMA(prices, fast) - EMA(prices, slow)
    📌 DEA = EMA(DIF, dea_period)
    📌 buffer 不足 (len < params.macd_min_ticks()) 或 NaN 返 None
    """
    if params is None:
        params = IndicatorParams.standard()
    if len(prices) < params.macd_min_ticks():
        return None
    if _has_nan(prices):
        return None
    ema_fast = _ema(prices, params.macd_fast)
    ema_slow = _ema(prices, params.macd_slow)
    if ema_fast is None or ema_slow is None:
        return None
    dif = ema_fast - ema_slow
    # DEA = EMA(DIF_series, dea_period) — 但需要 DIF 序列而非单点
    # 重新构造 DIF 序列：取最近 macd_slow + macd_dea - 1 根，逐根算 EMA 差
    window = prices[-(params.macd_slow + params.macd_dea - 1):]
    dif_series = []
    for i in range(params.macd_slow, len(window) + 1):
        sub = window[:i]
        ef = _ema(sub, params.macd_fast)
        es = _ema(sub, params.macd_slow)
        if ef is None or es is None:
            continue
        dif_series.append(ef - es)
    if len(dif_series) < params.macd_dea:
        return None
    dea = _ema(dif_series, params.macd_dea)
    if dea is None:
        return None
    bar = (dif - dea) * 2.0
    return (dif, dea, bar)


def compute_vol_avg(volumes: Sequence[int], period: int = 20) -> Optional[float]:
    """量能移动平均；buffer 不足或 NaN 返 None"""
    if period <= 0 or len(volumes) < period:
        return None
    if _has_nan([float(v) for v in volumes]):
        return None
    return sum(volumes[-period:]) / period


# ─────────────── 包级常量 / __all__ ───────────────


__all__ = [
    "IndicatorParams",
    "TickBuffer",
    "compute_ma",
    "compute_rsi",
    "compute_macd",
    "compute_vol_avg",
]