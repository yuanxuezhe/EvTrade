"""
api/stocks.py — 股票基础信息查询 REST 端点 (v23 slim-stocks-table)

端点:
- GET   /api/stocks                  列表(支持 ?sector= 筛选)
- GET   /api/stocks/{stock_code}     按代码查详情
- PATCH /api/stocks/{stock_code}     admin 编辑 stocks 行 (v22 stock-info-editor, v23 字段同步)

鉴权:
- GET: _AUTH (任意登录用户)
- PATCH: require_admin (admin only,内联覆盖)
"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.db import get_db
from server.auth.deps import require_admin
from server.repo import stocks as stocks_repo


router = APIRouter()


@router.get("")
async def list_stocks(sector: Optional[str] = None,
                       limit: int = 100, db=Depends(get_db)):
    """列出 stocks 表内容

    Args:
        sector: 板块筛选(可选)
        limit: 上限(默认 100)

    Returns:
        {code:0, msg:"ok", list:[{stock_code, stock_name, ...}, ...]}
    """
    from server.models.orm import Stock
    q = db.query(Stock)
    if sector:
        q = q.filter(Stock.sector == sector)
    q = q.order_by(Stock.stock_code).limit(limit)
    return {
        "code": 0,
        "msg": "ok",
        "list": [stocks_repo.to_dict(s) for s in q.all()],
    }


@router.get("/{stock_code}")
async def get_stock(stock_code: str, db=Depends(get_db)):
    """查单只股票基础信息

    Returns:
        {code:0, msg:"ok", data:{...}}
        404: not found
    """
    stock = stocks_repo.get_by_code(db, stock_code)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"stock {stock_code} not found")
    return {"code": 0, "msg": "ok", "data": stocks_repo.to_dict(stock)}


# ============================================================
# v22 stock-info-editor → v23 slim-stocks-table 字段同步
# ============================================================

class StockUpdateRequest(BaseModel):
    """admin 编辑 stocks 行的可编辑字段白名单(v23 5 字段精简版)

    所有字段可选 — 前端可能只改其中几个,Pydantic 默认 None。
    6 字段中 stock_code 是 PK(created_at/updated_at 由 DB 维护,不可改)
    → 实际可编辑 5 字段: stock_name/sector/is_t0_able/min_buy_qty/trade_unit

    v23 严格白名单:`extra=forbid` 让 industry/market/intro 等 9 旧字段
    在 Pydantic 层即抛 422(防 repo._ADMIN_EDITABLE_FIELDS 静默 drop 漏改)
    """
    stock_name: Optional[str] = Field(None, max_length=64)
    sector: Optional[str] = Field(None, max_length=64)
    is_t0_able: Optional[bool] = None
    min_buy_qty: Optional[int] = Field(None, ge=1)
    trade_unit: Optional[int] = Field(None, ge=1)

    class Config:
        extra = "forbid"


@router.patch("/{stock_code}", dependencies=[Depends(require_admin)])
async def update_stock(stock_code: str, body: StockUpdateRequest, db=Depends(get_db)):
    """admin 显式编辑单只股票基础信息(REQ-STOCK-003)

    Returns:
        {code:0, msg:"ok", data:{...}}  更新后的完整 stock
        404: stock_code 不存在
        400: body 为空(无字段需要更新)
    """
    payload = body.dict(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no fields to update")
    updated = stocks_repo.update_by_admin(db, stock_code, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"stock {stock_code} not found")
    return {"code": 0, "msg": "ok", "data": stocks_repo.to_dict(updated)}