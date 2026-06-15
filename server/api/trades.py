"""
trades.py — v5 重构版（schema refactor）

成交回报由 trd_cfm push handler 写入 trades 表。
GET /api/trades 纯读 DB，不调 RPC。

v5 改动：
- 移除 id 字段
- TRD_DATE → trd_date
- 复合主键 (trd_date, trade_id)
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
    trade_id: str
    trd_date: str
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
    trd_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    trd = trd_date or resolve_default_trd_date(db)
    q = db.query(Trade).filter(Trade.trd_date == trd)
    if stock_code:
        q = q.filter(Trade.stock_code == stock_code)
    # 排序：按 created_at 倒序（无 id 主键时不再用 id）
    rows = q.order_by(Trade.created_at.desc()).limit(500).all()
    return TradesListResponse(code=0, msg="", list=[
        TradeOut(
            trade_id=r.trade_id,
            trd_date=r.trd_date,
            order_id=r.order_id,
            stock_code=r.stock_code,
            order_type=r.order_type,
            price=r.price,
            volume=r.volume,
            amount=r.amount,
            trade_time=r.trade_time,
        ) for r in rows
    ])
