"""
admin/session.py — v4 交易时段配置

GET   /api/admin/trading-session   读
PATCH /api/admin/trading-session   改
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from db import get_db
from models.orm import TradingSession
from services.guards import require_admin

router = APIRouter()


class SessionOut(BaseModel):
    morning_start: str
    morning_end: str
    afternoon_start: str
    afternoon_end: str
    is_half_day: bool
    updated_at: Optional[str] = None


class SessionUpdate(BaseModel):
    morning_start: Optional[str] = None
    morning_end: Optional[str] = None
    afternoon_start: Optional[str] = None
    afternoon_end: Optional[str] = None
    is_half_day: Optional[bool] = None


@router.get("", response_model=SessionOut)
async def get_session(db: Session = Depends(get_db)):
    row = db.query(TradingSession).first()
    if not row:
        row = TradingSession()
        db.add(row)
        db.commit()
        db.refresh(row)
    return SessionOut(
        morning_start=row.morning_start.isoformat(),
        morning_end=row.morning_end.isoformat(),
        afternoon_start=row.afternoon_start.isoformat(),
        afternoon_end=row.afternoon_end.isoformat(),
        is_half_day=bool(row.is_half_day),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.patch("", response_model=SessionOut)
async def update_session(req: SessionUpdate, db: Session = Depends(get_db), _=Depends(require_admin)):
    row = db.query(TradingSession).first()
    if not row:
        row = TradingSession()
        db.add(row)
    for field in ('morning_start', 'morning_end', 'afternoon_start', 'afternoon_end'):
        v = getattr(req, field)
        if v:
            from datetime import time as dtime
            parts = v.split(':')
            setattr(row, field, dtime(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0))
    if req.is_half_day is not None:
        row.is_half_day = req.is_half_day
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    # 清缓存
    from services.trading_clock import TradingClock
    TradingClock._session_cache = None
    return SessionOut(
        morning_start=row.morning_start.isoformat(),
        morning_end=row.morning_end.isoformat(),
        afternoon_start=row.afternoon_start.isoformat(),
        afternoon_end=row.afternoon_end.isoformat(),
        is_half_day=bool(row.is_half_day),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )
