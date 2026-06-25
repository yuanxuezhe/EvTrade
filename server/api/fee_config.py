"""
fee_config.py — 费率配置路由（admin 可改）

GET   /api/fee-config
PATCH /api/fee-config  { commission_rate, stamp_tax_rate, slippage }
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from server.db import get_db
from server.models.orm import FeeConfig
from server.services.guards import require_admin
from server.services.push_helpers import format_db_dt

router = APIRouter()


class FeeConfigOut(BaseModel):
    commission_rate: float
    stamp_tax_rate: float
    slippage: float
    updated_at: Optional[str] = None


class FeeConfigUpdate(BaseModel):
    commission_rate: Optional[float] = None
    stamp_tax_rate: Optional[float] = None
    slippage: Optional[float] = None


@router.get("", response_model=FeeConfigOut)
async def get_fee_config_route(db: Session = Depends(get_db)):
    cfg = db.query(FeeConfig).first()
    if not cfg:
        cfg = FeeConfig(commission_rate=0.0001, stamp_tax_rate=0.001, slippage=0.0)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return FeeConfigOut(
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        slippage=cfg.slippage or 0.0,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )


@router.patch("", response_model=FeeConfigOut, dependencies=[Depends(require_admin)])
async def update_fee_config(req: FeeConfigUpdate, db: Session = Depends(get_db)):
    cfg = db.query(FeeConfig).first()
    if not cfg:
        cfg = FeeConfig()
        db.add(cfg)
    for field in ('commission_rate', 'stamp_tax_rate', 'slippage'):
        v = getattr(req, field)
        if v is not None:
            setattr(cfg, field, v)
    cfg.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(cfg)
    return FeeConfigOut(
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        slippage=cfg.slippage or 0.0,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )
