"""
server/strategy/lib/__init__.py — 暴露给用户脚本的 lib facade

📌 用户脚本 import 路径:
    from server.strategy.lib import MA, EMA, RSI, doorder, docancel, ...
    # 或者
    ctx.lib.MA(...)
    ctx.lib.doorder(...)

📌 实际暴露什么:
- indicators.py: MA, EMA, RSI, MACD, BOLL, KDJ, ATR, BARSLAST, REF, CROSS
- trading.py:    doorder, docancel, get_position (实际由 sandbox 注入, 这里仅占位)
"""
from server.strategy.lib.indicators import (
    MA, EMA, RSI, MACD, BOLL, KDJ, ATR, BARSLAST, REF, CROSS,
)
from server.strategy.lib.trading import (
    OrderError,
    SignalRecorder,
    doorder, docancel, get_position, signal,
    make_trading_facade,
)

__all__ = [
    # indicators
    "MA", "EMA", "RSI", "MACD", "BOLL", "KDJ", "ATR",
    "BARSLAST", "REF", "CROSS",
    # trading (占位, 由 sandbox 注入真实实现)
    "doorder", "docancel", "get_position", "signal",
    "OrderError", "SignalRecorder",
    "make_trading_facade",
]