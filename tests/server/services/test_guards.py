"""
test_guards.py — 验证屏障层
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from datetime import datetime, time, timedelta
from unittest.mock import patch
from fastapi import HTTPException

from db import Base, SessionLocal, init_db
from models.orm import SysStatus, TradingSession


@pytest.fixture(autouse=True)
def fresh_db():
    from db import engine
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


# ──── resolve_active_trd_date ────

def test_resolve_active_returns_none_when_no_active():
    db = SessionLocal()
    from services.guards import resolve_active_trd_date
    assert resolve_active_trd_date(db) is None
    db.close()


def test_resolve_active_returns_current_date():
    db = SessionLocal()
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    from services.guards import resolve_active_trd_date
    assert resolve_active_trd_date(db) == "20260614"
    db.close()


def test_resolve_active_ignores_closed_and_pending():
    db = SessionLocal()
    db.add(SysStatus(trd_date="20260613", status="closed"))
    db.add(SysStatus(trd_date="20260615", status="pending"))
    db.commit()
    from services.guards import resolve_active_trd_date
    assert resolve_active_trd_date(db) is None
    db.close()


# ──── resolve_default_trd_date ────

def test_default_uses_active():
    db = SessionLocal()
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    from services.guards import resolve_default_trd_date
    assert resolve_default_trd_date(db) == "20260614"
    db.close()


def test_default_falls_back_to_max():
    """未激活时查 MAX(trd_date) 兜底"""
    from sqlalchemy import text
    from models.orm import Order
    db = SessionLocal()
    db.add(Order(
        trd_date="20260613", order_id="OID1",
        user_def="CID1", order_no="10000001",
        stock_code="600030.SH",
        order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    from services.guards import resolve_default_trd_date
    assert resolve_default_trd_date(db) == "20260613"
    db.close()


def test_default_fallback_to_today():
    """全空时用今天"""
    db = SessionLocal()
    from services.guards import resolve_default_trd_date
    expected = datetime.now().strftime('%Y%m%d')
    assert resolve_default_trd_date(db) == expected
    db.close()


# ──── require_trading_day ────

@pytest.mark.asyncio
async def test_require_trading_day_blocks_when_not_init():
    from services.guards import require_trading_day
    with pytest.raises(HTTPException) as exc_info:
        await require_trading_day()
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "TRADING_DAY_NOT_INIT"


@pytest.mark.asyncio
async def test_require_trading_day_passes_when_active():
    db = SessionLocal()
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    db.close()
    from services.guards import require_trading_day
    result = await require_trading_day()
    assert result == "20260614"


# ──── TradingClock ────

def test_clock_morning_session():
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    db.close()
    from services.trading_clock import TradingClock
    TradingClock.invalidate_cache()
    fake = datetime(2026, 6, 14, 10, 30, 0)
    assert TradingClock.is_in_trading_session(fake) is True


def test_clock_lunch_break():
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    db.close()
    from services.trading_clock import TradingClock
    TradingClock.invalidate_cache()
    fake = datetime(2026, 6, 14, 12, 0, 0)
    assert TradingClock.is_in_trading_session(fake) is False


def test_clock_after_close():
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    db.close()
    from services.trading_clock import TradingClock
    TradingClock.invalidate_cache()
    fake = datetime(2026, 6, 14, 15, 30, 0)
    assert TradingClock.is_in_trading_session(fake) is False


def test_clock_pre_open():
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    db.close()
    from services.trading_clock import TradingClock
    TradingClock.invalidate_cache()
    fake = datetime(2026, 6, 14, 8, 0, 0)
    assert TradingClock.is_in_trading_session(fake) is False


def test_clock_half_day_skips_afternoon():
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.add(SysStatus(trd_date="20260614", status="active", is_half_day=1))
    db.commit()
    db.close()
    from services.trading_clock import TradingClock
    TradingClock.invalidate_cache()
    fake_morning = datetime(2026, 6, 14, 10, 0, 0)
    assert TradingClock.is_in_trading_session(fake_morning) is True
    fake_afternoon = datetime(2026, 6, 14, 14, 0, 0)
    assert TradingClock.is_in_trading_session(fake_afternoon) is False


def test_clock_creates_default_session_if_missing():
    db = SessionLocal()
    db.close()
    from services.trading_clock import TradingClock
    TradingClock.invalidate_cache()
    s = TradingClock._get_session()
    assert s.morning_start == time(9, 15)
    assert s.afternoon_end == time(15, 0)
