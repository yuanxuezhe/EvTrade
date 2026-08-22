"""
api/stocks.py — 股票基础信息查询 REST 端点

端点:
- GET   /api/stocks                  列表(真分页 page/page_size,服务端筛选 sector/keyword/is_t0_able)
- GET   /api/stocks/{stock_code}     按代码查详情
- PATCH /api/stocks/{stock_code}     admin 编辑 stocks 行
- POST  /api/stocks                  admin 添加 stocks 行 (8 字段白名单)

鉴权:
- GET: _AUTH (任意登录用户)
- PATCH/POST: require_admin (admin only,内联覆盖)
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from server.db import get_db
from server.auth.deps import require_admin
from server.repo import stocks as stocks_repo
from server.tables.stocks import Stocks


router = APIRouter()


# ============================================================
# GET 列表 — 真分页 + 服务端筛选
# ============================================================

@router.get("")
async def list_stocks(
    sector: Optional[str] = None,
    keyword: Optional[str] = None,         # 模糊匹配 stock_code 前缀或 stock_name 含
    is_t0_able: Optional[bool] = None,     # 回转标志过滤
    stktype: Optional[int] = None,          # 证券类型过滤 (0=股票 / 1=ETF, None=全部)
    page: int = 1,                          # 页码(默认 1)
    page_size: int = 100,                   # 每页大小(默认 100,范围 1..500)
    limit: Optional[int] = None,            # 兼容: 老客户端可继续用 limit(无 page/total 返回)
    db=Depends(get_db),
):
    """列出 stocks 表内容(真分页)

    查询参数:
      - sector: 板块子串匹配(可选, 不区分大小写 substring)
      - keyword: stock_code 前缀 OR stock_name 包含匹配(可选,大小写不敏感)
      - is_t0_able: 回转标志过滤(可选)
      - stktype: 证券类型过滤 (0=股票 / 1=ETF, None=全部)
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

    rows = Stocks.query_all()

    # 服务端筛选
    # sector 走子串匹配 ("消费" 匹配 "消费-白酒" / "消费品-零售")
    if sector:
        sec_q = sector.strip().lower()
        rows = [row for row in rows if (row.sector or '') and sec_q in row.sector.lower()]
    if is_t0_able is not None:
        rows = [row for row in rows if bool(row.is_t0_able) == is_t0_able]
    if stktype is not None:  # 证券类型过滤
        rows = [row for row in rows if row.stktype == stktype]
    if keyword:
        kw = keyword.strip().lower()
        # keyword 匹配 stock_code (包含) / stock_name (包含) / short_name (包含)
        rows = [
            row for row in rows
            if kw in row.stock_code.lower()
            or kw in (row.stock_name or "").lower()
            or kw in (row.short_name or "").lower()
        ]

    # total = COUNT(*),与 limit/page 无关
    total = len(rows)

    # 分页
    if limit is not None:
        # 老客户端兼容:limit 优先,不分页
        rows = sorted(rows, key=lambda row: row.stock_code)[:limit]
        return {
            "code": 0,
            "msg": "ok",
            "list": [stocks_repo.to_dict(s) for s in rows],
            "total": total,
        }

    # 真分页
    offset = (page - 1) * page_size
    rows = sorted(rows, key=lambda row: row.stock_code)[offset:offset + page_size]
    return {
        "code": 0,
        "msg": "ok",
        "list": [stocks_repo.to_dict(s) for s in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ============================================================
# GET 全量 - 前端 IndexedDB 首次/同步缓存用 (不分页, 1 次拉完)
# ============================================================

@router.get("/all")
async def list_all_stocks():
    """全量证券信息(前端缓存首次加载 / 同步刷新用, 不分页)

    Returns:
        {code:0, msg:"ok", list:[...], total:N}
        list 元素含 to_dict 全部 9 字段 (stock_code/stock_name/sector/is_t0_able/
        min_buy_qty/trade_unit/short_name/stktype/scale)
    """
    rows = sorted(Stocks.query_all(), key=lambda r: r.stock_code)
    return {
        "code": 0,
        "msg": "ok",
        "list": [stocks_repo.to_dict(s) for s in rows],
        "total": len(rows),
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
# PATCH — admin 编辑 stocks 行 (short_name 由 stock_name 自动生成)
# ============================================================

class StockUpdateRequest(BaseModel):
    """admin 编辑 stocks 行的可编辑字段白名单(8 字段, short_name 自动生成)

    所有字段可选 — 前端可能只改其中几个,Pydantic 默认 None。
    11 字段中 stock_code 是 PK,created_at/updated_at 由 DB 维护,不可改
    → 实际可编辑 8 字段: stock_name/sector/is_t0_able/min_buy_qty/trade_unit/stktype/scale
    (short_name 由 stock_name 自动派生, REQ-STOCK-007)

    严格白名单:`extra=forbid` 让 industry/market/intro 等旧字段
    在 Pydantic 层即抛 422(防 repo._ADMIN_EDITABLE_FIELDS 静默 drop 漏改)
    """
    stock_name: Optional[str] = Field(None, max_length=64)
    sector: Optional[str] = Field(None, max_length=64)
    is_t0_able: Optional[bool] = None
    min_buy_qty: Optional[int] = Field(None, ge=1)
    trade_unit: Optional[int] = Field(None, ge=1)
    stktype: Optional[int] = Field(None, ge=0, le=1)
    scale: Optional[int] = Field(None, ge=0, le=6)

    class Config:
        extra = "forbid"


@router.patch("/{stock_code}", dependencies=[Depends(require_admin)])
async def update_stock(stock_code: str, body: StockUpdateRequest, db=Depends(get_db)):
    """admin 显式编辑单只股票基础信息(REQ-STOCK-003 + REQ-STOCK-007)

    若 stock_name 字段被修改, 后端自动重算 short_name (REQ-STOCK-007)
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


# ============================================================
# POST — admin 手动添加
# ============================================================

# 证券代码正则:6 位数字 + .SH/.SZ/.BJ 后缀(A 股沪深京)
STOCK_CODE_REGEX = r"^\d{6}\.(SH|SZ|BJ)$"


class StockCreateRequest(BaseModel):
    """admin 添加 stocks 行的字段白名单(REQ-STOCK-006 + REQ-STOCK-007)

    11 字段:
    - stock_code: PK, 必填, regex 校验(000001.SZ / 600000.SH / 920169.BJ)
    - stock_name: 必填, max 64 (用于自动生成 short_name)
    - sector: 可选
    - is_t0_able / min_buy_qty / trade_unit: 有默认值
    - stktype / scale: 证券类型/价格精度, 有默认值
    (short_name 由 stock_name 自动派生, REQ-STOCK-007)

    严格白名单:`extra=forbid` 让 industry/market/intro 等旧字段
    在 Pydantic 层即抛 422(防数据脏)
    """
    stock_code: str = Field(..., pattern=STOCK_CODE_REGEX, max_length=16)
    stock_name: str = Field(..., min_length=1, max_length=64)
    sector: Optional[str] = Field(None, max_length=64)
    is_t0_able: bool = False
    min_buy_qty: int = Field(100, ge=1)
    trade_unit: int = Field(1, ge=1)
    stktype: int = Field(0, ge=0, le=1)
    scale: int = Field(2, ge=0, le=6)

    class Config:
        extra = "forbid"


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
async def create_stock(body: StockCreateRequest, db=Depends(get_db)):
    """admin 手动添加单只股票到 stocks 表(REQ-STOCK-006)

    Returns:
        {code:0, msg:"ok", data:{...}}  新插入的完整 stock
        409: stock_code 已存在
        422: 字段校验失败(由 Pydantic 自动处理)
    """
    payload = body.dict()
    new_stock = stocks_repo.create_by_admin(db, payload)
    if new_stock is None:
        raise HTTPException(
            status_code=409,
            detail=f"stock {body.stock_code} already exists"
        )
    return {"code": 0, "msg": "ok", "data": stocks_repo.to_dict(new_stock)}