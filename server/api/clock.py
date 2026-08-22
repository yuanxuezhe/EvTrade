"""
clock.py — 前端轮询接口

GET /api/trading/clock
"""
from datetime import datetime
from fastapi import APIRouter

from server.db import SessionLocal
from server.repo.system import TradingClock
from server.services.guards import resolve_default_trd_date, resolve_active_trd_date
from server.services import sysconfig  # 交易时段配置

router = APIRouter()


def _parse_trdtime(val: str):
    """解析 trdtime='093000-113000;130000-153000' → [{start,end},...]"""
    out = []
    if not val:
        return out
    for seg in val.split(";"):
        seg = seg.strip()
        if "-" not in seg:
            continue
        s, e = seg.split("-", 1)
        s, e = s.strip(), e.strip()
        if len(s) == 6 and len(e) == 6:
            out.append({"start": f"{s[:2]}:{s[2:4]}:{s[4:6]}", "end": f"{e[:2]}:{e[2:4]}:{e[4:6]}"})
    return out


@router.get("/clock")
async def get_trading_clock():
    """前端轮询用：交易日 + 时段状态"""
    db = SessionLocal()
    try:
        active_trd = resolve_active_trd_date(db)
        initialized = active_trd is not None
        default_trd = resolve_default_trd_date(db)
        is_in = TradingClock.is_in_trading_session()
        # 优先读 sysconfig.trdtime, 回退 TradingClock 默认值
        trdtime_raw = sysconfig.get_raw("trdtime", user="0") or "093000-113000;130000-153000"
        sessions = _parse_trdtime(trdtime_raw)
        win = {"morning": sessions[0] if len(sessions) >= 1 else {"start": "00:00:00", "end": "11:30:00"},
               "afternoon": sessions[1] if len(sessions) >= 2 else {"start": "11:30:00", "end": "23:59:00"},
               "is_half_day": False} if sessions else TradingClock.get_session_window()
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
