"""
api/stocks.py — 股票基础信息查询 REST 端点 (v21 stock-info-crawler)

端点:
- GET   /api/stocks                  列表(支持 ?industry= 筛选)
- GET   /api/stocks/{stock_code}     按代码查详情
- PATCH /api/stocks/{stock_code}     admin 编辑 stocks 行 (v22 stock-info-editor)

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
async def list_stocks(industry: Optional[str] = None, market: Optional[str] = None,
                       limit: int = 100, db=Depends(get_db)):
    """列出 stocks 表内容

    Args:
        industry: 行业筛选(可选)
        market: 市场筛选 SZ/SH(可选)
        limit: 上限(默认 100)

    Returns:
        {code:0, msg:"ok", list:[{stock_code, stock_name, ...}, ...]}
    """
    from server.models.orm import Stock
    q = db.query(Stock)
    if industry:
        q = q.filter(Stock.industry == industry)
    if market:
        q = q.filter(Stock.market == market)
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
# v22 stock-info-editor: PATCH /api/stocks/{stock_code} (admin only)
# ============================================================

class StockUpdateRequest(BaseModel):
    """admin 编辑 stocks 行的可编辑字段白名单

    所有字段可选 — 前端可能只改其中几个,Pydantic 默认 None。
    """
    stock_name: Optional[str] = Field(None, max_length=64)
    industry: Optional[str] = Field(None, max_length=64)
    sector: Optional[str] = Field(None, max_length=64)
    market: Optional[str] = Field(None, max_length=8)
    list_date: Optional[datetime] = None
    total_share: Optional[int] = Field(None, ge=0)
    float_share: Optional[int] = Field(None, ge=0)
    market_cap: Optional[float] = Field(None, ge=0)
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    intro: Optional[str] = None


@router.patch("/{stock_code}", dependencies=[Depends(require_admin)])
async def update_stock(stock_code: str, body: StockUpdateRequest, db=Depends(get_db)):
    """admin 显式编辑单只股票基础信息(REQ-STOCK-003)

    Returns:
        {code:0, msg:"ok", data:{...}}  更新后的完整 stock
        404: stock_code 不存在
        400: body 为空(无字段需要更新)
    """
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no fields to update")
    updated = stocks_repo.update_by_admin(db, stock_code, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"stock {stock_code} not found")
    return {"code": 0, "msg": "ok", "data": stocks_repo.to_dict(updated)}
