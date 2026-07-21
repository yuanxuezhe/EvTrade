"""
fee_config.py — 费率配置路由（admin 可改）

v78: 整合到 sysconfig 表后, 这里作为兼容层
- GET 优先读 sysconfig cache, cache miss 回退旧 fee_config 表
- PATCH 写 sysconfig (user='0' 默认), 同时同步旧表 (向后兼容)
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from server.auth.deps import get_current_user
from server.db import get_db
from server.models.orm import FeeConfig
from server.models.user import User
from server.services.guards import require_admin
from server.services import sysconfig

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
async def get_fee_config_route(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """v78: 优先读 sysconfig cache; cache miss 时回退旧 fee_config 表"""
    cr = sysconfig.get("commission_rate", 0.0001, user=_user.username)
    sr = sysconfig.get("stamp_tax_rate", 0.001, user=_user.username)
    sl = sysconfig.get("slippage", 0.001, user=_user.username)
    # cache miss 全为 None (说明 cache 未加载), 回退旧表
    if cr is None and sr is None and sl is None:
        cfg = db.query(FeeConfig).first()
        if cfg:
            cr, sr, sl = cfg.commission_rate, cfg.stamp_tax_rate, cfg.slippage or 0.0
    return FeeConfigOut(
        commission_rate=cr or 0.0001,
        stamp_tax_rate=sr or 0.001,
        slippage=sl or 0.0,
    )


@router.patch("", response_model=FeeConfigOut, dependencies=[Depends(require_admin)])
async def update_fee_config(req: FeeConfigUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v78: 写 sysconfig.user='0' 默认 + 同步旧 fee_config 表 (向后兼容)"""
    cr = sysconfig.get("commission_rate", 0.0001, user="0")
    sr = sysconfig.get("stamp_tax_rate", 0.001, user="0")
    sl = sysconfig.get("slippage", 0.001, user="0")
    if req.commission_rate is not None:
        cr = req.commission_rate
        sysconfig.set_value("0", "commission_rate", str(cr), "佣金费率 (万一)", user.username)
    if req.stamp_tax_rate is not None:
        sr = req.stamp_tax_rate
        sysconfig.set_value("0", "stamp_tax_rate", str(sr), "印花税率 (千一)", user.username)
    if req.slippage is not None:
        sl = req.slippage
        sysconfig.set_value("0", "slippage", str(sl), "滑点 (0.1%)", user.username)
    # 同步旧表 (向后兼容, 旧表保留只读)
    cfg = db.query(FeeConfig).first()
    if not cfg:
        cfg = FeeConfig()
        db.add(cfg)
    cfg.commission_rate = cr
    cfg.stamp_tax_rate = sr
    cfg.slippage = sl
    cfg.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(cfg)
    return FeeConfigOut(
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        slippage=cfg.slippage or 0.0,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )
