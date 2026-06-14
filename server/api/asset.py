"""
asset.py — v4 读本地 DB

资金由 ast_cfm push handler 写入 assets 表（单行 TRD_DATE）。
GET /api/asset 纯读 DB，不调 RPC。
"""
from fastapi import APIRouter, Depends
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models.orm import Asset
from services.guards import resolve_default_trd_date

router = APIRouter()


class AssetOut(BaseModel):
    TRD_DATE: str
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float
    synced_at: Optional[str] = None
    synced_from: str


class AssetResponse(BaseModel):
    code: int = 0
    msg: str = ""
    data: Optional[AssetOut] = None


@router.get("", response_model=AssetResponse)
async def get_account_asset(
    trading_day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    trd = trading_day or resolve_default_trd_date(db)
    row = db.query(Asset).filter(Asset.TRD_DATE == trd).first()
    if not row:
        return AssetResponse(code=0, msg="无资产数据", data=None)
    return AssetResponse(code=0, msg="", data=AssetOut(
        TRD_DATE=row.TRD_DATE,
        cash=row.cash,
        frozen_cash=row.frozen_cash,
        market_value=row.market_value,
        total_asset=row.total_asset,
        synced_at=row.synced_at.isoformat() if row.synced_at else None,
        synced_from=row.synced_from,
    ))
