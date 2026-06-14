"""
positions.py — v4 读本地 DB

持仓由 pos_cfm push handler 写入 positions 表。
GET /api/positions 纯读 DB，不调 RPC。
"""
from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models.orm import Position
from services.guards import resolve_default_trd_date

router = APIRouter()


class PositionOut(BaseModel):
    id: int
    TRD_DATE: str
    stock_code: str
    stock_name: str
    initial_position: int
    today_buy: int
    today_sell: int
    available: int
    total: int
    cost: float
    market_value: float
    synced_at: Optional[str] = None
    synced_from: str


class PositionsListResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[PositionOut] = []


@router.get("", response_model=PositionsListResponse)
async def list_positions(
    stock_code: Optional[str] = None,
    trading_day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    trd = trading_day or resolve_default_trd_date(db)
    q = db.query(Position).filter(Position.TRD_DATE == trd)
    if stock_code:
        q = q.filter(Position.stock_code == stock_code)
    rows = q.order_by(Position.stock_code).all()
    return PositionsListResponse(code=0, msg="", list=[
        PositionOut(
            id=r.id,
            TRD_DATE=r.TRD_DATE,
            stock_code=r.stock_code,
            stock_name=r.stock_name,
            initial_position=r.initial_position,
            today_buy=r.today_buy,
            today_sell=r.today_sell,
            available=r.available,
            total=r.total,
            cost=r.cost,
            market_value=r.market_value,
            synced_at=r.synced_at.isoformat() if r.synced_at else None,
            synced_from=r.synced_from,
        ) for r in rows
    ])
