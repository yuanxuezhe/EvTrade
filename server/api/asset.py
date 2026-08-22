"""
asset.py

资金由 day-init reconcile (server.services.reconcile.do_reconcile) 写入 assets 表（单行，无主键）。
GET /api/asset 纯读 DB，不调 RPC。
change consolidate-position-data-flow: ast_cfm push handler 已删除 (xtquant broker 不发)。

- synced_at 序列化为标准格式 "YYYY-MM-DD HH:MM:SS.fff" (format_db_dt)
- 装配 PUT /adjust 调平端点（admin 鉴权），实现见 server/api/asset_adjust.py
"""
from fastapi import APIRouter, Depends
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.tables.assets import Assets
from server.utils.time import format_db_dt
from server.api.asset_adjust import register_adjust

router = APIRouter()
register_adjust(router)  # PUT /adjust（admin 调平）


class AssetOut(BaseModel):
    cash: float
    available: float           # 可用资金 (= cash), 单独字段供前端直接读
    frozen_cash: float
    market_value: float
    total_asset: float
    last_asset: float          # 期初总资产 (早上 init 锁定, 当天不变, 前端算当日盈亏)
    synced_at: Optional[str] = None
    synced_from: str


class AssetResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[AssetOut] = []


@router.get("", response_model=AssetResponse)
async def get_account_asset(db: Session = Depends(get_db)):
    row = Assets.query_one(id=1)
    if not row:
        return AssetResponse(code=0, msg="无资产数据", list=[])
    # 兼容 RPC 还没推过来导致 row 没有 available 列 (例如重启瞬间老 ORM 实例化)
    _available = getattr(row, 'available', None)
    return AssetResponse(code=0, msg="", list=[AssetOut(
        cash=row.cash,
        available=float(_available) if _available is not None else float(row.cash or 0),
        frozen_cash=row.frozen_cash,
        market_value=row.market_value,
        total_asset=row.total_asset,
        last_asset=float(getattr(row, 'last_asset', 0) or 0),
        synced_at=format_db_dt(row.synced_at) if row.synced_at else None,
        synced_from=row.synced_from,
    )])


@router.get("/rpc-status")
async def get_rpc_status():
    """返回 RPC 通信健康状态"""
    from server.services.rpc_health import get_status
    return get_status()
