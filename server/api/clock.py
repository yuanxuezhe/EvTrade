"""
clock.py — 前端轮询接口

GET /api/trading/clock
"""
from datetime import datetime
from fastapi import APIRouter

from server.db import SessionLocal
from server.repo.system import TradingClock
from server.services.guards import resolve_default_trd_date, resolve_active_trd_date

router = APIRouter()


@router.get("/clock")
async def get_trading_clock():
    """前端轮询用：交易日 + 时段状态"""
    db = SessionLocal()
    try:
        active_trd = resolve_active_trd_date(db)
        initialized = active_trd is not None
        default_trd = resolve_default_trd_date(db)
        is_in = TradingClock.is_in_trading_session()
        win = TradingClock.get_session_window()
        nxt = TradingClock.next_session_start()
        secs = TradingClock.seconds_until_session()
    finally:
        db.close()

    return {
        "trading_day": active_trd,
        "trading_day_initialized": initialized,
        "default_trading_day": default_trd,
        "is_in_session": is_in,
        "current_time": datetime.now().isoformat(),
        "session_window": win,
        "next_session_start": nxt.isoformat() if nxt else None,
        "seconds_until_session": secs,
    }
