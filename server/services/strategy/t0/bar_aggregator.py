"""
strategy/t0/bar_aggregator.py — tick → 5分钟K线聚合

📌 对齐 A 股交易时段：09:30-11:30, 13:00-15:00
📌 每根 bar 对齐标准 5 分钟边界（09:30/09:35/...）
📌 午间休市（11:30-13:00）自动 close 当前 bar，13:00 开新 bar
📌 保留最近 50 根已完成 bar + 当前累积 bar

时间计算使用本地时区（Asia/Shanghai, UTC+8），与 hqserver tick 一致。
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional


@dataclass
class Bar:
    """一根 5 分钟 K 线"""
    period_start: int            # bar 起始时间（分钟数，如 09:30 → 570）
    open: float
    high: float
    low: float
    close: float
    volume: int = 0              # 成交量累加
    amount: float = 0.0          # 成交额累加
    tick_count: int = 0          # tick 数


# ─────────────── 交易时段常量 ───────────────

MORNING_START = 570              # 09:30
MORNING_END = 690                # 11:30
AFTERNOON_START = 780            # 13:00
AFTERNOON_END = 900              # 15:00
LUNCH_BREAK_START = MORNING_END  # 11:30


def _minutes_since_midnight(dt: datetime) -> int:
    """datetime → 分钟数（hour * 60 + minute）"""
    return dt.hour * 60 + dt.minute


def _is_trading_time(minutes: int) -> bool:
    """是否在交易时段内"""
    return (MORNING_START <= minutes < MORNING_END or
            AFTERNOON_START <= minutes < AFTERNOON_END)


def _bar_boundary(minutes: int, bar_minutes: int = 5) -> int:
    """向下取整到 bar 边界（5 分钟对齐，基于 MORNING_START）

    例: 09:32 → 09:30 (570), 09:37 → 09:35 (575)
    下午: 14:02 → 14:00 (840)
    """
    if minutes < MORNING_START:
        return MORNING_START
    if MORNING_START <= minutes < MORNING_END:
        return MORNING_START + ((minutes - MORNING_START) // bar_minutes) * bar_minutes
    if AFTERNOON_START <= minutes < AFTERNOON_END:
        return AFTERNOON_START + ((minutes - AFTERNOON_START) // bar_minutes) * bar_minutes
    return MORNING_START


@dataclass
class BarAggregator:
    """滚动 5 分钟 K 线聚合器

    📌 add_tick(tick) → Optional[Bar]（bar 完成时返回已完成的 bar）
    📌 get_bars(n) → 最后 n 根已完成 bar
    📌 reset() → 清空所有（每个交易日开盘调用）
    """
    bar_minutes: int = 5
    max_bars: int = 50

    _completed: Deque[Bar] = field(default_factory=lambda: deque(maxlen=50))
    _current: Optional[Bar] = None
    _current_start: int = 0

    def reset(self) -> None:
        """清空所有 bar（每日开盘调用）"""
        self._completed.clear()
        self._current = None
        self._current_start = 0

    def add_tick(self, tick: dict) -> Optional[Bar]:
        """加入一个 tick，如果当前 bar 已跨越边界则关闭并返回完成的 bar。

        tick 需要包含: last_price, volume(可选), amount(可选)
        时间从 tick 的 datetime 字段获取（格式: 'yyyyMMddHHmmss' 或 datetime 对象）
        如果 tick 没有时间字段，使用 last_time 属性。
        """
        price = tick.get("last_price")
        if price is None:
            return None
        price = float(price)

        # 解析时间
        minutes = self._extract_minutes(tick)
        if minutes is None:
            return None

        if not _is_trading_time(minutes):
            return None

        bar_start = _bar_boundary(minutes, self.bar_minutes)

        # 首次初始化
        if self._current is None:
            self._current_start = bar_start
            self._current = Bar(
                period_start=bar_start,
                open=price, high=price, low=price, close=price,
            )
            self._update_current(tick)
            return None

        # 跨越 bar 边界 → 关闭当前 bar
        if bar_start != self._current_start:
            completed = self._close_bar()
            self._current_start = bar_start
            self._current = Bar(
                period_start=bar_start,
                open=price, high=price, low=price, close=price,
            )
            self._update_current(tick)
            return completed

        # 休市间隙（上午 → 下午）
        if (self._current_start < MORNING_END and
                minutes >= AFTERNOON_START):
            completed = self._close_bar()
            self._current_start = bar_start
            self._current = Bar(
                period_start=bar_start,
                open=price, high=price, low=price, close=price,
            )
            self._update_current(tick)
            return completed

        # 同一 bar 内更新
        self._update_current(tick)
        return None

    def _extract_minutes(self, tick: dict) -> Optional[int]:
        """从 tick 中提取分钟数（hour*60 + minute）。

        tick 来源:
        1. quote_consumer._parse_tick() → fields[1] = 'yyyyMMddHHmmss.sss'
        2. snapshot dict → 无时间字段
        3. 单测 mock → 可能直接传 _minutes 或 datetime
        """
        # 1. 优先直接字段（单测友好）
        if "_minutes" in tick:
            return int(tick["_minutes"])

        # 2. fields[1] = 'yyyyMMddHHmmss.sss'（quote_consumer 解析格式）
        fields = tick.get("fields") or []
        if len(fields) > 1 and fields[1]:
            dt_str = str(fields[1])
            if len(dt_str) >= 12:
                try:
                    return int(dt_str[8:10]) * 60 + int(dt_str[10:12])
                except (ValueError, IndexError):
                    pass

        # 3. datetime 字段（标准格式）
        dt = tick.get("datetime") or tick.get("time")
        if isinstance(dt, datetime):
            return _minutes_since_midnight(dt)
        if isinstance(dt, str) and len(dt) >= 12:
            try:
                return int(dt[8:10]) * 60 + int(dt[10:12])
            except (ValueError, IndexError):
                pass

        return None

    def _update_current(self, tick: dict) -> None:
        """用 tick 更新当前 bar 的 OHLCV"""
        if self._current is None:
            return
        p = float(tick["last_price"])
        v = int(tick.get("volume") or 0)
        a = float(tick.get("amount") or 0.0)
        self._current.high = max(self._current.high, p)
        self._current.low = min(self._current.low, p)
        self._current.close = p
        self._current.volume = max(self._current.volume, v)   # 累计成交量取最大（绝对值）
        self._current.amount = max(self._current.amount, a)
        self._current.tick_count += 1

    def _close_bar(self) -> Optional[Bar]:
        """关闭当前 bar，加入已完成队列"""
        if self._current is None:
            return None
        bar = self._current
        self._completed.append(bar)
        self._current = None
        return bar

    def get_bars(self, n: int = 20) -> List[Bar]:
        """返回最近 n 根已完成 bar"""
        bars = list(self._completed)
        return bars[-n:] if n < len(bars) else bars

    def get_current_bar(self) -> Optional[Bar]:
        """返回当前正在累积的 bar（未关闭）"""
        return self._current

    def get_closes(self, n: int = 20) -> List[float]:
        """返回最近 n 根 bar 的收盘价（含当前 bar）"""
        bars = list(self._completed)
        closes = [b.close for b in bars[-n:]]
        if self._current and len(bars) >= n:
            closes = closes[:-1] + [self._current.close]
        elif self._current:
            closes.append(self._current.close)
        return closes

    def get_all_closes(self) -> List[float]:
        """返回所有 bar 的收盘价（含当前 bar）"""
        closes = [b.close for b in self._completed]
        if self._current:
            closes.append(self._current.close)
        return closes


__all__ = ["Bar", "BarAggregator", "MORNING_START", "MORNING_END",
           "AFTERNOON_START", "AFTERNOON_END"]
