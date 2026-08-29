"""
strategy_exec.market_data.aggregator — broker 1m close → 用户指定 period 聚合

📌 broker his_hq 只返 1m close (用户 2026-08-30 实测确认). 其他 period
   (5m / 15m / 30m / 60m / 1d) 在 strategy_exec 端按 1m + 时间戳聚合.

设计:
- 纯函数 (无 IO), 单测友好
- 输入: 1m K 线数组 [{stime: "20250102093100", close: "100.0"}, ...]
- 输出: 聚合后 K 线 [{stime, open, high, low, close, volume}, ...]
- stime 格式: 1m 输入 14位 YYYYMMDDHHMMSS; 输出
    - 1d  → YYYYMMDD150000 (15:00 收盘, Backtrader format="%Y%m%d%H%MSS" 兼容)
    - 其余 → YYYYMMDDHHMMSS (5m/15m/... 桶起点, e.g. 09:30 / 09:35 / 09:45)
- volume: broker 1m close 不带, aggregator 不造数据, 输出 0 (与 broker 行为一致)

A 股交易日历 (1d 聚合):
- 跳过 Sat/Sun (broker 1m 数据本身不含周末, 兜底)
- 交易时段: 09:31~11:30 + 13:01~15:00 (broker 1m 数据自动覆盖, 兜底)
- 午休 11:31~12:59 1m 数据空 (broker 自动跳过)
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, List

log = logging.getLogger(__name__)

# 支持的 period (1d/1h/1m/5m/15m/30m/60m)
_PERIOD_TO_BUCKET_SIZE = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1h": 60,   # alias
}

# A股交易时段 (用于 1d 聚合 边界判断)
_MORNING_END_HHMMSS = "113000"  # 11:30:00
_AFTERNOON_START_HHMMSS = "130100"  # 13:01:00
_AFTERNOON_END_HHMMSS = "150000"  # 15:00:00
_DAY_END_STIME_SUFFIX = "150000"  # 1d 输出用 (15:00 收盘)


def _parse_stime(stime: str) -> _dt.datetime:
    """stime 14位 'YYYYMMDDHHMMSS' → datetime."""
    if len(stime) < 14:
        # 兼容 8位 'YYYYMMDD' (1d 1m 数据 padding 后)
        if len(stime) == 8:
            return _dt.datetime.strptime(stime + _DAY_END_STIME_SUFFIX, "%Y%m%d%H%M%S")
        raise ValueError(f"stime 格式不支持: {stime!r}")
    return _dt.datetime.strptime(stime[:14], "%Y%m%d%H%M%S")


def _format_stime(dt: _dt.datetime, period: str) -> str:
    """datetime → stime 字符串."""
    if period == "1d":
        # 1d 输出 YYYYMMDD150000 (15:00 收盘, Backtrader format="%Y%m%d%H%MSS" 兼容)
        return dt.strftime("%Y%m%d") + _DAY_END_STIME_SUFFIX
    return dt.strftime("%Y%m%d%H%M%S")


def _bucket_key(dt: _dt.datetime, bucket_minutes: int) -> _dt.datetime:
    """1m datetime → 桶起点 datetime (按 bucket_minutes 对齐)."""
    if bucket_minutes == 1:
        return dt.replace(second=0, microsecond=0)
    # 对齐到 N 分钟起点 (e.g. 5min桶: 09:30, 09:35, 09:40, ...)
    minute = (dt.minute // bucket_minutes) * bucket_minutes
    return dt.replace(minute=minute, second=0, microsecond=0)


def aggregate_bars(
    bars_1m: List[Dict[str, Any]],
    user_period: str,
) -> List[Dict[str, Any]]:
    """1m K 线数组 → 用户指定 period 的 K 线.

    Args:
        bars_1m: broker 返回的 1m close 数据, 每项 {'stime': 'YYYYMMDDHHMMSS', 'close': str|float, ...}
        user_period: '1m' / '5m' / '15m' / '30m' / '60m' / '1h' / '1d'

    Returns:
        聚合后 K 线: [{'stime', 'open', 'high', 'low', 'close', 'volume'}, ...]
        按 stime 升序

    Raises:
        ValueError: 不支持的 period
    """
    if user_period == "1d":
        return _aggregate_1d(bars_1m)
    if user_period not in _PERIOD_TO_BUCKET_SIZE:
        raise ValueError(
            f"unsupported period={user_period!r}, supported: {list(_PERIOD_TO_BUCKET_SIZE) + ['1d']}"
        )
    return _aggregate_intraday(bars_1m, user_period, _PERIOD_TO_BUCKET_SIZE[user_period])


def _aggregate_intraday(
    bars_1m: List[Dict[str, Any]], period: str, bucket_minutes: int,
) -> List[Dict[str, Any]]:
    """5m/15m/30m/60m 聚合 — 按固定 N 分钟桶对齐."""
    if not bars_1m:
        return []

    # 按桶分组: {bucket_start_dt: [bars]}
    buckets: Dict[_dt.datetime, List[Dict[str, Any]]] = {}
    for bar in bars_1m:
        stime_str = str(bar.get("stime", ""))
        if not stime_str:
            continue
        try:
            dt = _parse_stime(stime_str)
        except (ValueError, TypeError) as e:
            log.warning("[aggregator] skip bad stime %r: %s", stime_str, e)
            continue
        bk = _bucket_key(dt, bucket_minutes)
        buckets.setdefault(bk, []).append(bar)

    # 聚合每个桶
    out: List[Dict[str, Any]] = []
    for bk in sorted(buckets.keys()):
        bars = buckets[bk]
        if not bars:
            continue
        out.append(_aggregate_one_bucket(bars, _format_stime(bk, period)))
    return out


def _aggregate_1d(bars_1m: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """1d 聚合 — 按 A 股交易日历 (跳过周末 + 午休 11:31~12:59)."""
    if not bars_1m:
        return []

    # 按日期分桶 (stime[:8] = YYYYMMDD)
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for bar in bars_1m:
        stime_str = str(bar.get("stime", ""))
        if len(stime_str) < 8:
            continue
        date_str = stime_str[:8]
        try:
            date = _dt.datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError as e:
            log.warning("[aggregator] skip bad date %r: %s", date_str, e)
            continue
        # 跳过周末 (兜底, broker 1m 数据本身不含)
        if date.weekday() >= 5:  # 5=Sat, 6=Sun
            continue
        buckets.setdefault(date_str, []).append(bar)

    out: List[Dict[str, Any]] = []
    for date_str in sorted(buckets.keys()):
        bars = buckets[date_str]
        if not bars:
            continue
        out.append(_aggregate_one_bucket(bars, date_str + _DAY_END_STIME_SUFFIX))
    return out


def _aggregate_one_bucket(
    bars: List[Dict[str, Any]], stime_str: str,
) -> Dict[str, Any]:
    """单桶聚合 — OHLCV: open=第一根, close=最后一根, high=max, low=min, volume=sum."""
    if not bars:
        return {}

    opens: List[float] = []
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []

    for bar in bars:
        c = _to_float(bar.get("close"))
        if c is not None:
            closes.append(c)
        o = _to_float(bar.get("open"))
        if o is not None:
            opens.append(o)
        h = _to_float(bar.get("high"))
        if h is not None:
            highs.append(h)
        l = _to_float(bar.get("low"))
        if l is not None:
            lows.append(l)
        v = _to_float(bar.get("volume"))
        if v is not None:
            volumes.append(v)

    # open/high/low: 优先用 broker 字段 (虽然 1m 返 0), 兜底用 close
    open_price = opens[0] if opens else (closes[0] if closes else 0.0)
    close_price = closes[-1] if closes else (opens[-1] if opens else 0.0)
    high_price = max(highs) if highs else max(closes) if closes else open_price
    low_price = min(lows) if lows else min(closes) if closes else open_price
    volume = sum(volumes)

    return {
        "stime": stime_str,
        "open": round(open_price, 4),
        "high": round(high_price, 4),
        "low": round(low_price, 4),
        "close": round(close_price, 4),
        "volume": int(volume) if volume else 0,
    }


def _to_float(v: Any) -> float | None:
    """str/float/int/None → float|None. broker 1m close 是 str, 需转换."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None