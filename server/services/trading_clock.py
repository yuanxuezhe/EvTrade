"""
trading_clock.py — 交易时段判断

- 缓存 TradingSession 配置 60s
- 半天（is_half_day）走 morning 段
- is_in_trading_session() 协程安全（无状态）
"""
from datetime import datetime, time as dtime
from typing import Optional
from db import SessionLocal
from models.orm import TradingSession, TradingDay


class TradingClock:
    _session: Optional[TradingSession] = None
    _is_half_day: bool = False
    _loaded_at: Optional[datetime] = None
    CACHE_TTL_SEC = 60

    @classmethod
    def _get_session(cls) -> TradingSession:
        if (cls._session and cls._loaded_at
                and (datetime.now() - cls._loaded_at).total_seconds() < cls.CACHE_TTL_SEC):
            return cls._session
        db = SessionLocal()
        try:
            row = db.query(TradingSession).first()
            if not row:
                from datetime import time
                row = TradingSession(
                    morning_start=time(9, 15), morning_end=time(11, 30),
                    afternoon_start=time(13, 0), afternoon_end=time(15, 0),
                )
                db.add(row); db.commit()
                db.refresh(row)
            cls._session = row
            # 半天判断
            active = db.query(TradingDay).filter_by(status='active').first()
            cls._is_half_day = bool(active and active.is_half_day)
            cls._loaded_at = datetime.now()
            return row
        finally:
            db.close()

    @classmethod
    def is_in_trading_session(cls, now: Optional[datetime] = None) -> bool:
        s = cls._get_session()
        t = (now or datetime.now()).time()
        if s.morning_start <= t <= s.morning_end:
            return True
        # 半天：跳过下午
        if cls._is_half_day:
            return False
        if s.afternoon_start <= t <= s.afternoon_end:
            return True
        return False

    @classmethod
    def get_session_window(cls) -> dict:
        s = cls._get_session()
        return {
            "morning":   {"start": s.morning_start.isoformat(),   "end": s.morning_end.isoformat()},
            "afternoon": {"start": s.afternoon_start.isoformat(), "end": s.afternoon_end.isoformat()},
            "is_half_day": cls._is_half_day,
        }

    @classmethod
    def next_session_start(cls) -> Optional[dtime]:
        s = cls._get_session()
        now = datetime.now()
        t = now.time()
        if t < s.morning_start:
            return s.morning_start
        if s.morning_end < t < s.afternoon_start:
            return s.afternoon_start
        # 当前在上午段且非半天：下一个段是下午
        if s.morning_start <= t <= s.morning_end and not cls._is_half_day:
            return s.afternoon_start
        # 下午段：下一天
        if t > s.afternoon_end:
            return s.morning_start
        return None

    @classmethod
    def seconds_until_session(cls) -> int:
        nxt = cls.next_session_start()
        if not nxt:
            return 0
        now = datetime.now()
        nxt_dt = now.replace(hour=nxt.hour, minute=nxt.minute, second=nxt.second, microsecond=0)
        if nxt_dt < now:
            # 明天
            from datetime import timedelta
            nxt_dt += timedelta(days=1)
        return int((nxt_dt - now).total_seconds())

    @classmethod
    def invalidate_cache(cls):
        cls._session = None
        cls._loaded_at = None
