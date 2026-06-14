"""
trades.py — v4 读本地 DB

成交回报由 trd_cfm push handler 写入 trades 表。
GET /api/trades 纯读 DB，不调 RPC。
"""
from fastapi import APIRouter, Depends
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models.orm import Trade
from services.guards import resolve_default_trd_date

router = APIRouter()


class TradeOut(BaseModel):
    id: int
    trade_id: str
    TRD_DATE: str
    order_id: str
    stock_code: str
    order_type: str
    price: float
    volume: int
    amount: float
    trade_time: str


class TradesListResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[TradeOut] = []


@router.get("", response_model=TradesListResponse)
async def list_trades(
    stock_code: Optional[str] = None,
    trading_day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    trd = trading_day or resolve_default_trd_date(db)
    q = db.query(Trade).filter(Trade.TRD_DATE == trd)
    if stock_code:
        q = q.filter(Trade.stock_code == stock_code)
    rows = q.order_by(Trade.id.desc()).limit(500).all()
    return TradesListResponse(code=0, msg="", list=[
        TradeOut(
            id=r.id,
            trade_id=r.trade_id,
            TRD_DATE=r.TRD_DATE,
            order_id=r.order_id,
            stock_code=r.stock_code,
            order_type=r.order_type,
            price=r.price,
            volume=r.volume,
            amount=r.amount,
            trade_time=r.trade_time,
        ) for r in rows
    ])
