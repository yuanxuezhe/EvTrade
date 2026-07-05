"""
strategy — 量价标志注册表 + 检测器（change strategy_trade task 4）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-002
📌 9 种 flag（spec line 61 明确"共 9 项"）：trend × 4 / oscillator × 2 / volume × 1 / momentum × 2
📌 检测入口 `detect_flags(buffer, params, prev_close)` 返 Set[str]
📌 任何依赖 indicator 的 flag 在 buffer 不足时静默跳过（None 不进 Set）
📌 price_change_* 需要 prev_close；prev_close=None 时跳过

阈值（spec 表定义，写死）：
  - RSI 70 / 30
  - vol ≥ 2× MA_VOL(20)
  - 涨跌幅 ±1%
  - MACD cross：DIF vs DEA 1 根前穿越

后续扩展：阈值也可走 IndicatorParams（v1 暂用常量；切换 preset 时保留入口）
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from server.services.strategy.indicators import (
    TickBuffer,
    IndicatorParams,
    compute_ma,
    compute_rsi,
    compute_macd,
    compute_vol_avg,
)


# ─────────────── Flag 数据结构 ───────────────


@dataclass(frozen=True)
class FlagDef:
    """单个 flag 的元数据 + 触发条件描述（前端展示用）。"""
    code: str          # 'ma_bullish'
    name: str          # '均线多头'
    category: str      # 'trend' / 'oscillator' / 'volume' / 'momentum'
    description: str   # 触发条件（中文短描述）


# ─────────────── 9-flag 注册表（dict 保持插入顺序，前端按此序展示） ───────────────


FLAG_REGISTRY: Dict[str, FlagDef] = {
    "ma_bullish":        FlagDef("ma_bullish",        "均线多头", "trend",      "MA5>MA10>MA20"),
    "ma_bearish":        FlagDef("ma_bearish",        "均线空头", "trend",      "MA5<MA10<MA20"),
    "rsi_overbought":    FlagDef("rsi_overbought",    "RSI超买",  "oscillator", "RSI(6) ≥ 70"),
    "rsi_oversold":      FlagDef("rsi_oversold",      "RSI超卖",  "oscillator", "RSI(6) ≤ 30"),
    "vol_breakout":      FlagDef("vol_breakout",      "量能突破", "volume",     "当根 vol ≥ 2× MA_VOL(20)"),
    "price_change_up":   FlagDef("price_change_up",   "涨幅≥1%",  "momentum",   "(last-prev_close)/prev_close ≥ 0.01"),
    "price_change_down": FlagDef("price_change_down", "跌幅≤-1%",  "momentum",   "(last-prev_close)/prev_close ≤ -0.01"),
    "macd_golden_cross": FlagDef("macd_golden_cross", "MACD金叉", "trend",      "DIF>DEA 且 1 根前 DIF≤DEA"),
    "macd_death_cross":  FlagDef("macd_death_cross",  "MACD死叉", "trend",      "DIF<DEA 且 1 根前 DIF≥DEA"),
}


# ─────────────── 阈值常量（spec 表定义，写死） ───────────────

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
VOL_BREAKOUT_MULT = 2.0
PRICE_CHANGE_UP = 0.01
PRICE_CHANGE_DOWN = -0.01


# ─────────────── 私有 detect 函数（每个 ≤15 行） ───────────────


def _detect_ma_flags(prices, params: IndicatorParams) -> Set[str]:
    """MA 多 / 空头：MA_short > MA_mid > MA_long 或反向"""
    if not params.ma_periods or len(params.ma_periods) < 3:
        return set()
    short, mid, long_p = params.ma_periods[0], params.ma_periods[1], params.ma_periods[2]
    ma_s = compute_ma(prices, short)
    ma_m = compute_ma(prices, mid)
    ma_l = compute_ma(prices, long_p)
    if ma_s is None or ma_m is None or ma_l is None:
        return set()
    out = set()
    if ma_s > ma_m > ma_l:
        out.add("ma_bullish")
    if ma_s < ma_m < ma_l:
        out.add("ma_bearish")
    return out


def _detect_rsi_flags(prices, params: IndicatorParams) -> Set[str]:
    """RSI 超买 / 超卖"""
    rsi = compute_rsi(prices, params.rsi_period)
    if rsi is None:
        return set()
    out = set()
    if rsi >= RSI_OVERBOUGHT:
        out.add("rsi_overbought")
    if rsi <= RSI_OVERSOLD:
        out.add("rsi_oversold")
    return out


def _detect_vol_flag(buffer: TickBuffer, params: IndicatorParams) -> Set[str]:
    """当根 vol ≥ 2× MA_VOL(period)"""
    vols = buffer.volumes()
    if len(vols) < params.vol_period + 1:
        return set()
    avg = compute_vol_avg(vols[:-1], params.vol_period)  # 用前 N 根算基准
    if avg is None or avg <= 0:
        return set()
    if vols[-1] >= VOL_BREAKOUT_MULT * avg:
        return {"vol_breakout"}
    return set()


def _detect_price_change_flags(last_price: Optional[float], prev_close: Optional[float]) -> Set[str]:
    """涨跌幅 ≥±1%（prev_close 缺失时跳过）"""
    if last_price is None or prev_close is None or prev_close <= 0:
        return set()
    change = (last_price - prev_close) / prev_close
    out = set()
    if change >= PRICE_CHANGE_UP:
        out.add("price_change_up")
    if change <= PRICE_CHANGE_DOWN:
        out.add("price_change_down")
    return out


def _detect_macd_cross_flags(prices, params: IndicatorParams) -> Set[str]:
    """MACD 金叉 / 死叉：当前 DIF/DEA 与前一根 DIF/DEA 穿越"""
    if len(prices) < 2:
        return set()
    curr = compute_macd(prices, params)
    prev = compute_macd(prices[:-1], params)
    if curr is None or prev is None:
        return set()
    dif_c, dea_c, _ = curr
    dif_p, dea_p, _ = prev
    out = set()
    if dif_c > dea_c and dif_p <= dea_p:
        out.add("macd_golden_cross")
    if dif_c < dea_c and dif_p >= dea_p:
        out.add("macd_death_cross")
    return out


# ─────────────── 检测入口（公共 API） ───────────────


def detect_flags(
    buffer: TickBuffer,
    params: IndicatorParams = None,
    prev_close: Optional[float] = None,
) -> Set[str]:
    """扫一遍所有 9 个 flag，返回当前活跃的 flag code 集合。

    📌 buffer 不足或 prev_close 缺失时对应 flag 静默跳过，不抛错
    📌 params=None → 用 IndicatorParams.standard() 默认 12/26/9 + MA5/10/20 + RSI(6)
    📌 后续接入"市场状态识别"模块自动切换 params 时，只改调用方，flags.py 不动
    """
    if params is None:
        params = IndicatorParams.standard()

    prices = buffer.prices()
    last_tick = buffer.last()
    last_price = last_tick.get("last_price") if last_tick else None

    active: Set[str] = set()
    active |= _detect_ma_flags(prices, params)
    active |= _detect_rsi_flags(prices, params)
    active |= _detect_vol_flag(buffer, params)
    active |= _detect_price_change_flags(last_price, prev_close)
    active |= _detect_macd_cross_flags(prices, params)
    return active


def get_flag_definitions() -> List[Dict[str, str]]:
    """按 FLAG_REGISTRY 顺序返 [{code, name, category, description}, ...]（前端 API 用）。"""
    return [
        {"code": fd.code, "name": fd.name, "category": fd.category, "description": fd.description}
        for fd in FLAG_REGISTRY.values()
    ]


__all__ = ["FlagDef", "FLAG_REGISTRY", "detect_flags", "get_flag_definitions"]