"""
asset.py — v5 重构版（schema refactor）

资金由 day-init reconcile (server.services.reconcile.do_reconcile) 写入 assets 表（单行，无主键）。
GET /api/asset 纯读 DB，不调 RPC。
change consolidate-position-data-flow: ast_cfm push handler 已删除 (xtquant broker 不发)。

v5 改动：
- 移除 TRD_DATE 字段（assets 只保存当前资金）
- 移除 id 字段

v10 改动（rpc-field-alignment-ts-unify）：
- synced_at 序列化为标准格式 "YYYY-MM-DD HH:MM:SS.fff" (format_db_dt)
"""
from fastapi import APIRouter, Depends
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.models.orm import Asset
from server.utils.time import format_db_dt

router = APIRouter()


class AssetOut(BaseModel):
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float
    synced_at: Optional[str] = None
    synced_from: str


class AssetResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[AssetOut] = []


@router.get("", response_model=AssetResponse)
async def get_account_asset(db: Session = Depends(get_db)):
    row = db.query(Asset).first()
    if not row:
        return AssetResponse(code=0, msg="无资产数据", list=[])
    return AssetResponse(code=0, msg="", list=[AssetOut(
        cash=row.cash,
        frozen_cash=row.frozen_cash,
        market_value=row.market_value,
        total_asset=row.total_asset,
        synced_at=format_db_dt(row.synced_at) if row.synced_at else None,
        synced_from=row.synced_from,
    )])
