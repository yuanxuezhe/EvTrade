"""
trades.py — v5 重构版（schema refactor）

成交回报由 trd_cfm push handler 写入 trades 表。
GET /api/trades 纯读 DB，不调 RPC。

v5 改动：
- 移除 id 字段
- TRD_DATE → trd_date
- 复合主键 (trd_date, trade_id)

v10 改动（order-trade-query-by-trd-date）：
- 新增 query 入参 start_date / end_date (区间模式: start_date <= trd_date <= end_date)
- 缺省模式: trd_date = 激活日 (向后兼容)
- 排序: created_at DESC → trade_time DESC, trade_id DESC
  - trade_time 同秒时 trade_id 二级稳定排序
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional, List
from pydantic import BaseModel

from server.db import get_db
from server.tables.trades import Trades
from server.services.guards import resolve_default_trd_date

router = APIRouter()


class TradeOut(BaseModel):
    trade_id: str
    trd_date: str
    order_no: str
    stock_code: str
    order_type: str
    price: float
    volume: int
    amount: float
    trade_time: str
    trade_type: int = 0  # v9: 0=normal 1=cancel-fill (本地代理撤单成交行)


class TradesListResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[TradeOut] = []


@router.get("", response_model=TradesListResponse)
async def list_trades(
    stock_code: Optional[str] = None,
    trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，缺省 = 激活日"),
    start_date: Optional[str] = Query(
        None, regex=r"^\d{8}$",
        description="起始交易日 YYYYMMDD（含）",
    ),
    end_date: Optional[str] = Query(
        None, regex=r"^\d{8}$",
        description="结束交易日 YYYYMMDD（含）",
    ),
):
    """成交列表

    过滤语义:
    - start_date/end_date 任一存在 → 走区间模式 (start_date <= trd_date <= end_date)
    - 都不存在 → 走缺省模式 (trd_date = 激活日, 向后兼容)
    - 区间模式优先级高于 trd_date: start_date/end_date 存在时 trd_date 被忽略

    排序: trade_time DESC, trade_id DESC (v10, trade_time 同秒时 trade_id 二级稳定)
    """
    rows = Trades.query_all()

    if start_date or end_date:
        if start_date:
            rows = [row for row in rows if row.trd_date >= start_date]
        if end_date:
            rows = [row for row in rows if row.trd_date <= end_date]
    else:
        trd = trd_date or resolve_default_trd_date(db)
        rows = [row for row in rows if row.trd_date == trd]

    if stock_code:
        rows = [row for row in rows if row.stock_code == stock_code]

    rows = sorted(rows, key=lambda row: (row.trade_time, row.trade_id), reverse=True)[:500]
    return TradesListResponse(code=0, msg="", list=[
        TradeOut(
            trade_id=r.trade_id,
            trd_date=r.trd_date,
            order_no=r.order_no,
            stock_code=r.stock_code,
            order_type=r.order_type,
            price=r.price,
            volume=r.volume,
            amount=r.amount,
            trade_time=r.trade_time,
            trade_type=r.trade_type or 0,
        ) for r in rows
    ])
