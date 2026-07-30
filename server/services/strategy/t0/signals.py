"""
strategy/t0/signals.py — 三大信号模型检测 + 统一入口

📌 1. VWAP 乖离率回归模型
📌 2. 开盘30分钟冲高/急跌模型
📌 3. 5分钟布林线触轨突破模型

所有检测函数返回 List[T0Signal]，无副作用纯函数。
"""
from typing import List, Optional

from server.services.strategy.t0.models import (
    T0Signal, T0StrategyParams,
    T0VWAPParams, T0OpeningParams, T0BollingerParams,
)
from server.services.strategy.t0.bar_aggregator import (
    Bar, MORNING_START, MORNING_END, AFTERNOON_START, AFTERNOON_END,
)
from server.services.strategy.t0.t0_indicators import (
    compute_vwap_deviation,
    compute_bollinger_bands,
    detect_lower_shadow,
    detect_zhiting_yangxian,
    detect_insufficient_volume,
    classify_volume_trend,
)
from server.services.strategy.indicators import compute_rsi


# ─────────────── 1. VWAP 乖离率回归 ───────────────

def detect_vwap_signals(
    current_price: float,
    vwap: float,
    current_bar: Optional[Bar],
    prev_bars: List[Bar],
    params: T0VWAPParams,
    now_ts: float = 0.0,
) -> List[T0Signal]:
    """VWAP 乖离率回归模型。

    买入(正T): deviation < -buy_deviation_low 且 (if require_kline_signal,
               current_bar 下影线或止跌阳线)
    卖出(倒T): deviation > sell_deviation_low 且 量能不足
    平仓: |deviation| < close_deviation
    """
    signals: List[T0Signal] = []
    if vwap <= 0:
        return signals

    deviation = compute_vwap_deviation(current_price, vwap)

    # 买入信号（急跌偏离）
    if deviation <= -params.buy_deviation_low:
        strength = 0.8 if deviation <= -params.buy_deviation_high else 0.6
        if params.require_kline_signal and current_bar:
            if not (detect_lower_shadow(current_bar) or detect_zhiting_yangxian(current_bar)):
                pass  # 无 K 线确认，不触发
            else:
                signals.append(T0Signal(
                    signal_type="vwap_buy",
                    model="vwap",
                    direction="buy",
                    price=current_price,
                    volume=0,  # 由 engine 填充
                    reason=f"VWAP偏离 {deviation:.2%}，K线止跌",
                    strength=strength,
                    timestamp=now_ts,
                ))
        elif not params.require_kline_signal:
            signals.append(T0Signal(
                signal_type="vwap_buy",
                model="vwap",
                direction="buy",
                price=current_price,
                volume=0,
                reason=f"VWAP偏离 {deviation:.2%}",
                strength=strength,
                timestamp=now_ts,
            ))

    # 卖出信号（急拉偏离 + 量能不足）
    if deviation >= params.sell_deviation_low:
        strength = 0.8 if deviation >= params.sell_deviation_high else 0.6
        vol_check = True
        if current_bar and prev_bars:
            vol_check = detect_insufficient_volume(current_bar, prev_bars)
        if vol_check:
            signals.append(T0Signal(
                signal_type="vwap_sell",
                model="vwap",
                direction="sell",
                price=current_price,
                volume=0,
                reason=f"VWAP偏离 {deviation:.2%}，量能不足",
                strength=strength,
                timestamp=now_ts,
            ))

    # 平仓信号（回归 VWAP）
    signals.append(T0Signal(
        signal_type="close_position",
        model="vwap",
        direction="close",
        price=current_price,
        volume=0,
        reason=f"回归VWAP，偏离 {deviation:.2%}",
        strength=0.3,
        timestamp=now_ts,
    )) if abs(deviation) < params.close_deviation else None

    return signals


# ─────────────── 2. 开盘30分钟冲高/急跌 ───────────────

def detect_opening_signals(
    current_price: float,
    open_price: float,
    current_time_minutes: int,
    volume_trend: str,
    params: T0OpeningParams,
    now_ts: float = 0.0,
) -> List[T0Signal]:
    """开盘30分钟冲高/急跌模型。

    倒T: 开盘10分钟内无利好大幅冲高，且量能未持续放大
    正T: 开盘急跌超阈值，且无恐慌巨量
    """
    signals: List[T0Signal] = []
    if open_price <= 0:
        return signals

    # 仅开盘后 params.opening_period_minutes 分钟内有效
    elapsed = current_time_minutes - MORNING_START
    if elapsed < 0 or elapsed > params.opening_period_minutes:
        return signals

    change_from_open = (current_price - open_price) / open_price

    # 急冲卖出（倒T）：冲高 > surge_threshold，且在卖出窗口内
    if (change_from_open >= params.surge_threshold and
            params.sell_window_start <= current_time_minutes <= params.sell_window_end and
            volume_trend not in ("increasing", "panic")):
        signals.append(T0Signal(
            signal_type="opening_sell",
            model="opening",
            direction="sell",
            price=current_price,
            volume=0,
            reason=f"开盘冲高 {change_from_open:.2%}，量能未跟进",
            strength=0.7,
            timestamp=now_ts,
        ))

    # 急跌买入（正T）：急跌 > drop_threshold，且无恐慌巨量
    if (change_from_open <= -params.drop_threshold and
            volume_trend != "panic"):
        signals.append(T0Signal(
            signal_type="opening_buy",
            model="opening",
            direction="buy",
            price=current_price,
            volume=0,
            reason=f"开盘急跌 {abs(change_from_open):.2%}，无恐慌巨量",
            strength=0.7,
            timestamp=now_ts,
        ))

    return signals


# ─────────────── 3. 5分钟布林线触轨 ───────────────

def detect_bollinger_signals(
    current_price: float,
    all_closes: List[float],
    params: T0BollingerParams,
    now_ts: float = 0.0,
) -> List[T0Signal]:
    """5分钟布林线触轨突破模型。

    买入: price < lower_band 且 RSI(6) < rsi_oversold
    卖出: price > upper_band 且 RSI(6) > rsi_overbought
    """
    signals: List[T0Signal] = []

    bb = compute_bollinger_bands(all_closes, params.period, params.std_mult)
    if bb is None:
        return signals

    upper, middle, lower = bb

    # RSI 确认
    rsi = compute_rsi(all_closes, params.rsi_period) if len(all_closes) >= params.rsi_period + 1 else None

    # 买入：跌破下轨 + RSI 超卖
    if current_price < lower and rsi is not None and rsi < params.rsi_oversold:
        signals.append(T0Signal(
            signal_type="bb_buy",
            model="bollinger",
            direction="buy",
            price=current_price,
            volume=0,
            reason=f"跌破布林下轨({lower:.2f})，RSI={rsi:.1f}",
            strength=0.75,
            timestamp=now_ts,
        ))

    # 卖出：突破上轨 + RSI 超买
    if current_price > upper and rsi is not None and rsi > params.rsi_overbought:
        signals.append(T0Signal(
            signal_type="bb_sell",
            model="bollinger",
            direction="sell",
            price=current_price,
            volume=0,
            reason=f"突破布林上轨({upper:.2f})，RSI={rsi:.1f}",
            strength=0.75,
            timestamp=now_ts,
        ))

    return signals


# ─────────────── 统一入口 ───────────────

def detect_all_signals(
    current_price: float,
    vwap: float,
    current_bar: Optional[Bar],
    prev_bars: List[Bar],
    all_closes: List[float],
    open_price: float,
    prev_close: float,
    current_time_minutes: int,
    volume_trend: str,
    params: T0StrategyParams,
    now_ts: float = 0.0,
) -> List[T0Signal]:
    """检测所有启用模型的信号，合并 + 优先级排序。

    优先级：close_position > vwap > opening > bollinger
    """
    all_signals: List[T0Signal] = []

    if "vwap" in params.models_enabled:
        all_signals.extend(detect_vwap_signals(
            current_price, vwap, current_bar, prev_bars,
            params.vwap, now_ts,
        ))

    if "opening" in params.models_enabled:
        all_signals.extend(detect_opening_signals(
            current_price, open_price, current_time_minutes,
            volume_trend, params.opening, now_ts,
        ))

    if "bollinger" in params.models_enabled:
        all_signals.extend(detect_bollinger_signals(
            current_price, all_closes, params.bollinger, now_ts,
        ))

    # 优先级排序：close_position 优先，然后按 strength 降序
    priority = {"close_position": 0, "vwap_buy": 1, "vwap_sell": 2,
                "opening_sell": 3, "opening_buy": 4,
                "bb_sell": 5, "bb_buy": 6}
    all_signals.sort(key=lambda s: (priority.get(s.signal_type, 9), -s.strength))

    return all_signals


__all__ = [
    "detect_vwap_signals",
    "detect_opening_signals",
    "detect_bollinger_signals",
    "detect_all_signals",
]
