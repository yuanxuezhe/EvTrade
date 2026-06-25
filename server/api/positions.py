"""
positions.py — v5 重构版（schema refactor）

持仓由 pos_cfm push handler + do_reconcile 写入 positions 表。
GET /api/positions 纯读 DB，不调 RPC。

v5 改动：
- 移除 id、TRD_DATE 字段
- initial_position → last_vol
- available → avl_vol
- total → vol
- cost → cost_price
- 主键 stock_code
- 持仓是「当前快照」语义，不分交易日

v10 改动（rpc-field-alignment-ts-unify）：
- synced_at 序列化为标准格式 "YYYY-MM-DD HH:MM:SS.fff" (format_db_dt)

NOTE: market_value 字段
- 后端不存 market_value（Position ORM 无此列）
- 前端用 quote store 实时重算真实市值
- 此处用 cost_price * vol 作为「成本市值」代理
"""
from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.models.orm import Position
from server.services.push_helpers import format_db_dt

router = APIRouter()


class PositionOut(BaseModel):
    stock_code: str
    stock_name: str
    last_vol: int
    today_buy: int
    today_sell: int
    avl_vol: int
    vol: int
    cost_price: float
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
    db: Session = Depends(get_db),
):
    q = db.query(Position)
    if stock_code:
        q = q.filter(Position.stock_code == stock_code)
    rows = q.order_by(Position.stock_code).all()
    return PositionsListResponse(code=0, msg="", list=[
        PositionOut(
            stock_code=r.stock_code,
            stock_name=r.stock_name,
            last_vol=r.last_vol,
            today_buy=r.today_buy,
            today_sell=r.today_sell,
            avl_vol=r.avl_vol,
            vol=r.vol,
            cost_price=r.cost_price,
            # 成本市值代理：cost_price * vol；前端用 quote store 实时重算真实市值
            market_value=round(r.cost_price * r.vol, 2),
            synced_at=format_db_dt(r.synced_at) if r.synced_at else None,
            synced_from=r.synced_from,
        ) for r in rows
    ])
