"""
positions.py

持仓由 trd_cfm push handler (intra-day 增量, Position.vol) + do_reconcile (day-init 全表覆盖) 写入 positions 表。
change consolidate-position-data-flow: pos_cfm push handler 已删除 (xtquant broker 不发)。
GET /api/positions 纯读 DB，不调 RPC。

- positions 表: 主键 stock_code, 字段 last_vol / avl_vol / vol / cost_price
- 持仓是「当前快照」语义，不分交易日
- synced_at 序列化为标准格式 "YYYY-MM-DD HH:MM:SS.fff" (format_db_dt)
- 装配 PUT /{stock_code}/adjust 调平端点（admin 鉴权），实现见 server/api/position_adjust.py

NOTE: market_value 字段
- 后端不存 market_value（Position ORM 无此列）
- 前端用 quote store 实时重算真实市值
- 此处用 cost_price * vol 作为「成本市值」代理
"""
from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel

from server.db import get_db
from server.tables import Positions
from server.utils.time import format_db_dt
from server.api.position_adjust import register_adjust

router = APIRouter()
register_adjust(router)  # PUT /{stock_code}/adjust（admin 调平）


class PositionOut(BaseModel):
    stock_code: str
    stock_name: str
    last_vol: int
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
):
    # 走 Positions.query_by / query_one
    # Positions.__pk_fields__ = ('stock_code',) → 默认按 stock_code 升序
    if stock_code:
        rows = Positions.query_by("stock_code", stock_code)
    else:
        rows = Positions.query_all()
    return PositionsListResponse(code=0, msg="", list=[
        PositionOut(
            stock_code=r.stock_code,
            stock_name=r.stock_name,
            last_vol=r.last_vol,
            avl_vol=r.avl_vol,
            vol=r.vol,
            cost_price=r.cost_price,
            # 成本市值代理：cost_price * vol；前端用 quote store 实时重算真实市值
            market_value=round(r.cost_price * r.vol, 2),
            synced_at=format_db_dt(r.synced_at) if r.synced_at else None,
            synced_from=r.synced_from,
        ) for r in rows
    ])
