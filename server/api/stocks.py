"""
api/stocks.py — 股票基础信息查询 REST 端点
v25 stocks-cache-and-short-name: 真分页 page/page_size + total 返回 + short_name 白名单

端点:
- GET   /api/stocks                  列表(真分页 page/page_size,服务端筛选 sector/keyword/is_t0_able)
- GET   /api/stocks/{stock_code}     按代码查详情
- PATCH /api/stocks/{stock_code}     admin 编辑 stocks 行 (v22 stock-info-editor, v23 字段同步, v25 +short_name)

鉴权:
- GET: _AUTH (任意登录用户)
- PATCH: require_admin (admin only,内联覆盖)
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func

from server.db import get_db
from server.auth.deps import require_admin
from server.repo import stocks as stocks_repo


router = APIRouter()


# ============================================================
# GET 列表 — v25 真分页 + 服务端筛选
# ============================================================

@router.get("")
async def list_stocks(
    sector: Optional[str] = None,
    keyword: Optional[str] = None,         # v25 新增: 模糊匹配 stock_code 前缀或 stock_name 含
    is_t0_able: Optional[bool] = None,     # v25 新增: 回转标志过滤
    page: int = 1,                          # v25 新增: 页码(默认 1)
    page_size: int = 100,                   # v25 新增: 每页大小(默认 100,范围 1..500)
    limit: Optional[int] = None,            # v23 兼容: 老客户端可继续用 limit(无 page/total 返回)
    db=Depends(get_db),
):
    """列出 stocks 表内容(v25 真分页)

    查询参数:
      - sector: 板块精确匹配(可选)
      - keyword: stock_code 前缀 OR stock_name 包含匹配(可选,大小写不敏感)
      - is_t0_able: 回转标志过滤(可选)
      - page: 页码,默认 1,≥ 1
      - page_size: 每页大小,默认 100,1..500
      - limit: 兼容老客户端(优先用 page_size)

    Returns:
      {code:0, msg:"ok", list:[...], total:N, page, page_size}
    """
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 500:
        raise HTTPException(status_code=400, detail="page_size must be in 1..500")

    from server.models.orm import Stock
    base_q = db.query(Stock)

    # 服务端筛选
    if sector:
        base_q = base_q.filter(Stock.sector == sector)
    if is_t0_able is not None:
        base_q = base_q.filter(Stock.is_t0_able == is_t0_able)
    if keyword:
        kw = f"%{keyword.strip()}%"
        # 优先 stock_code 前缀,其次 stock_name 含
        # MySQL 用 LIKE 模糊匹配 + 函数 LOWER 不必要(主键 stock_code 是数字+字母)
        base_q = base_q.filter(
            (Stock.stock_code.like(kw)) | (Stock.stock_name.like(kw))
        )

    # total = COUNT(*),与 limit/page 无关
    total = base_q.with_entities(sa_func.count(Stock.stock_code)).scalar() or 0

    # 分页
    if limit is not None:
        # 老客户端兼容:limit 优先,不分页
        rows = base_q.order_by(Stock.stock_code).limit(limit).all()
        return {
            "code": 0,
            "msg": "ok",
            "list": [stocks_repo.to_dict(s) for s in rows],
            "total": total,
        }

    # 真分页
    offset = (page - 1) * page_size
    rows = (
        base_q.order_by(Stock.stock_code)
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "msg": "ok",
        "list": [stocks_repo.to_dict(s) for s in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ============================================================
# GET 详情
# ============================================================

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
# PATCH — v22 stock-info-editor → v23 slim-stocks-table → v25 +short_name
# ============================================================

class StockUpdateRequest(BaseModel):
    """admin 编辑 stocks 行的可编辑字段白名单(v25 6 字段 + short_name = 7 字段)

    所有字段可选 — 前端可能只改其中几个,Pydantic 默认 None。
    8 字段中 stock_code 是 PK(created_at/updated_at 由 DB 维护,不可改)
    → 实际可编辑 7 字段: stock_name/sector/is_t0_able/min_buy_qty/trade_unit/short_name

    v23 严格白名单:`extra=forbid` 让 industry/market/intro 等 9 旧字段
    在 Pydantic 层即抛 422(防 repo._ADMIN_EDITABLE_FIELDS 静默 drop 漏改)
    v25: 加 short_name 字段(可选,空字符串清空)
    """
    stock_name: Optional[str] = Field(None, max_length=64)
    sector: Optional[str] = Field(None, max_length=64)
    is_t0_able: Optional[bool] = None
    min_buy_qty: Optional[int] = Field(None, ge=1)
    trade_unit: Optional[int] = Field(None, ge=1)
    short_name: Optional[str] = Field(None, max_length=16)  # v25: 拼音首字母简称

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