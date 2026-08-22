"""
holdings.py

持仓精简视图（与 /api/positions 共享同一张 positions 表，但字段裁剪为 6 列）
GET /api/holdings 纯读 DB，不调 RPC。
"""
from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.tables import Positions

router = APIRouter()


class HoldingItem(BaseModel):
    stock_code: str
    last_vol: int    # 期初
    vol: int         # 总持仓
    avl_vol: int     # 可用
    cost_price: float
    market_value: float


class HoldingsListResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[HoldingItem] = []


@router.get("", response_model=HoldingsListResponse)
async def list_holdings(
    stock_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """读本地 positions 表（走 Positions.*）"""
    # Positions.__pk_fields__ = ('stock_code',) → 默认按 stock_code 升序
    if stock_code:
        rows = Positions.query_by("stock_code", stock_code)
    else:
        rows = Positions.query_all()
    return HoldingsListResponse(code=0, msg="", list=[
        HoldingItem(
            stock_code=r.stock_code,
            last_vol=r.last_vol,
            vol=r.vol,
            avl_vol=r.avl_vol,
            cost_price=r.cost_price,
            # 成本市值代理：cost_price * vol；前端用 quote store 实时重算真实市值
            market_value=round(r.cost_price * r.vol, 2),
        ) for r in rows
    ])
