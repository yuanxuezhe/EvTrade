"""
strategy_exec.market_data.mock_history — broker his_hq 离线 mock K 线生成器

📌 Linux dev 环境无 xtquant / QMT broker 时, 走此 mock 通道让回测端到端跑通.
   触发: sys_config.user='0' AND cfg_key='his_hq_test_mode' = '1'
   (切换: scripts/evctl.py set-his-hq-test-mode 0|1)

设计要点:
- 确定性: 同 stock_code + 同区间 = 同 K 线 (跨重启一致), 基于 hash(stock_code) 做 RNG seed
- 数据 schema 与 broker msgpacket 协议对齐: {stime, open, high, low, close, volume}
- 跳过周末 (Sat/Sun)
- period=1d 完整实现; 其他 period 暂返空 (后续扩展)
- 起始价 50~150 区间, 随机游走 gauss(0, 0.02) 日涨跌幅
- OHLC 关系: high ≥ max(open, close); low ≤ min(open, close)
"""
from __future__ import annotations

import datetime as _dt
import logging
import random
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# 支持的 period (其他返空)
_SUPPORTED_PERIODS = frozenset({"1d"})


def _seed_from_stock(stock_code: str) -> int:
    """同 stock_code + 同区间 = 同数据, 跨重启一致"""
    return abs(hash(stock_code)) % (2**31)


def _iter_workdays(start_date: str, end_date: str):
    """迭代区间内所有工作日 (Mon-Fri), 跳过周末.

    Args:
        start_date / end_date: YYYYMMDD
    Yields:
        YYYYMMDD 字符串
    """
    s = _dt.datetime.strptime(start_date[:8], "%Y%m%d").date()
    e = _dt.datetime.strptime(end_date[:8], "%Y%m%d").date()
    if s > e:
        return
    cur = s
    while cur <= e:
        if cur.weekday() < 5:  # 0=Mon, 4=Fri
            yield cur.strftime("%Y%m%d")
        cur += _dt.timedelta(days=1)


def generate_mock_bars(
    stock_code: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """生成 mock K 线 (确定性, 同 stock_code 同区间 = 同数据)

    Args:
        stock_code: 标的代码 (用于 hash seed)
        start_date / end_date: YYYYMMDD
        period: 周期 (仅 1d 完整支持, 其他返空)
        seed: 可选自定义 seed (默认 hash(stock_code))

    Returns:
        [{"stime": "20250102", "open": 100.0, "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
        工作日数根 K 线 (周末跳过)
    """
    if period not in _SUPPORTED_PERIODS:
        log.warning(
            "[mock_history] period=%r 不在支持列表 %s, 返空 (后续扩展)",
            period, sorted(_SUPPORTED_PERIODS),
        )
        return []

    if seed is None:
        seed = _seed_from_stock(stock_code)
    rng = random.Random(seed)

    # 起始价 50~150 (确保 OHLC 有合理范围)
    last_close = 50.0 + (seed % 100)

    bars: List[Dict[str, Any]] = []
    for stime in _iter_workdays(start_date, end_date):
        # daily stime = YYYYMMDDHHMMSS (14 位, 对齐 broker 协议 + Backtrader 解析)
        #   period=1d → 15:00:00 (A股收盘时刻, 15:00:00.000000)
        stime_dt = f"{stime}150000"
        # 日涨跌幅 gauss(0, 0.02) → 0.02 σ (约 2% 日波)
        daily_return = rng.gauss(0.0, 0.02)
        open_price = last_close
        close_price = max(1.0, open_price * (1.0 + daily_return))
        # high/low 在 open/close 上下浮动
        intra_range = abs(close_price - open_price) + open_price * rng.uniform(0.005, 0.015)
        high_price = max(open_price, close_price) + intra_range * rng.uniform(0.0, 0.5)
        low_price = min(open_price, close_price) - intra_range * rng.uniform(0.0, 0.5)
        # 强约束 OHLC 关系
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price, max(1.0, low_price))
        # volume: 基准 100万 + seed 微扰
        volume = 1_000_000 + int(rng.uniform(-100_000, 100_000))
        volume = max(100_000, volume)

        bars.append({
            "stime": stime_dt,
            "open": round(open_price, 4),
            "high": round(high_price, 4),
            "low": round(low_price, 4),
            "close": round(close_price, 4),
            "volume": volume,
        })
        last_close = close_price

    log.info(
        "[mock_history] generated %d bars stock=%s %s~%s period=%s seed=%d",
        len(bars), stock_code, start_date, end_date, period, seed,
    )
    return bars