"""
api/stocks.py — 股票基础信息查询 REST 端点 (v21 stock-info-crawler)

端点:
- GET /api/stocks                  列表(支持 ?industry= 筛选)
- GET /api/stocks/{stock_code}     按代码查详情

鉴权: _AUTH (任意登录用户)
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException

from server.db import SessionLocal
from server.repo import stocks as stocks_repo


router = APIRouter()


@router.get("")
async def list_stocks(industry: Optional[str] = None, market: Optional[str] = None,
                       limit: int = 100):
    """列出 stocks 表内容

    Args:
        industry: 行业筛选(可选)
        market: 市场筛选 SZ/SH(可选)
        limit: 上限(默认 100)

    Returns:
        {code:0, msg:"ok", list:[{stock_code, stock_name, ...}, ...]}
    """
    db = SessionLocal()
    try:
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
    finally:
        db.close()


@router.get("/{stock_code}")
async def get_stock(stock_code: str):
    """查单只股票基础信息

    Returns:
        {code:0, msg:"ok", data:{...}}
        404: not found
    """
    db = SessionLocal()
    try:
        stock = stocks_repo.get_by_code(db, stock_code)
        if stock is None:
            raise HTTPException(status_code=404, detail=f"stock {stock_code} not found")
        return {"code": 0, "msg": "ok", "data": stocks_repo.to_dict(stock)}
    finally:
        db.close()