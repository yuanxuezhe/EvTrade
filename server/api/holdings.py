"""
holdings.py — v5 读本地 DB（v4 漏改端点）

持仓由 pos_cfm push handler + do_reconcile 写入 positions 表。
GET /api/holdings 纯读 DB，不调 RPC。返回 6 字段精简版。

NOTE: market_value 字段
- v4 实施时 Position ORM 漏了 market_value 字段（v4 bug，详见
  change `2026-06-15-fix-position-market-value-field`）
- 此处临时用 cost × total 作为「成本市值」代理，前端持仓页用 quote store
  liveMarketValue 实时重算真实市值（holdings.js:83-97）
"""
from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models.orm import Position
from services.guards import resolve_default_trd_date

router = APIRouter()


class HoldingItem(BaseModel):
    stock_code: str
    initial_position: int   # 旧 last_vol 字段，DB 语义对齐
    total: int              # 旧 volume 字段，DB 语义对齐
    available: int
    cost: float
    market_value: float


class HoldingsListResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[HoldingItem] = []


@router.get("", response_model=HoldingsListResponse)
async def list_holdings(
    stock_code: Optional[str] = None,
    trading_day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """读本地 positions 表。trading_day 默认 = 激活日，缺失回退到 MAX(TRD_DATE)。"""
    trd = trading_day or resolve_default_trd_date(db)
    q = db.query(Position).filter(Position.TRD_DATE == trd)
    if stock_code:
        q = q.filter(Position.stock_code == stock_code)
    rows = q.order_by(Position.stock_code).all()
    return HoldingsListResponse(code=0, msg="", list=[
        HoldingItem(
            stock_code=r.stock_code,
            initial_position=r.initial_position,
            total=r.total,
            available=r.available,
            cost=r.cost,
            # 成本市值代理：cost × total；前端用 quote store 实时重算真实市值
            market_value=round(r.cost * r.total, 2),
        ) for r in rows
    ])
