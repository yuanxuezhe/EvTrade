"""
fee_config.py — 费率配置路由（admin 可改）

GET   /api/fee-config
PATCH /api/fee-config  { commission_rate, min_commission, ... }
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from db import get_db
from models.orm import FeeConfig
from services.guards import require_admin

router = APIRouter()


class FeeConfigOut(BaseModel):
    commission_rate: float
    min_commission: float
    stamp_tax_rate: float
    transfer_fee_rate: float
    updated_at: Optional[str] = None


class FeeConfigUpdate(BaseModel):
    commission_rate: Optional[float] = None
    min_commission: Optional[float] = None
    stamp_tax_rate: Optional[float] = None
    transfer_fee_rate: Optional[float] = None


@router.get("", response_model=FeeConfigOut)
async def get_fee_config_route(db: Session = Depends(get_db)):
    cfg = db.query(FeeConfig).first()
    if not cfg:
        cfg = FeeConfig(commission_rate=0.0001, min_commission=5.0,
                        stamp_tax_rate=0.0005, transfer_fee_rate=0.00001)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return FeeConfigOut(
        commission_rate=cfg.commission_rate,
        min_commission=cfg.min_commission,
        stamp_tax_rate=cfg.stamp_tax_rate,
        transfer_fee_rate=cfg.transfer_fee_rate,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )


@router.patch("", response_model=FeeConfigOut, dependencies=[Depends(require_admin)])
async def update_fee_config(req: FeeConfigUpdate, db: Session = Depends(get_db)):
    from datetime import datetime
    cfg = db.query(FeeConfig).first()
    if not cfg:
        cfg = FeeConfig()
        db.add(cfg)
    for field in ('commission_rate', 'min_commission', 'stamp_tax_rate', 'transfer_fee_rate'):
        v = getattr(req, field)
        if v is not None:
            setattr(cfg, field, v)
    cfg.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cfg)
    return FeeConfigOut(
        commission_rate=cfg.commission_rate,
        min_commission=cfg.min_commission,
        stamp_tax_rate=cfg.stamp_tax_rate,
        transfer_fee_rate=cfg.transfer_fee_rate,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )
