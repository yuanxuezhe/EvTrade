"""
fee_config.py — 费率配置路由（admin 可改）

v_next: 整合到 sysconfig 表后, 不再访问旧 fee_config 表
- GET/PATCH 完全走 sysconfig (user='0' 默认)
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from server.auth.deps import get_current_user
from server.models.user import User
from server.services.guards import require_admin
from server.services import sysconfig

router = APIRouter()


class FeeConfigOut(BaseModel):
    commission_rate: float
    stamp_tax_rate: float
    slippage: float
    min_commission: float
    updated_at: Optional[str] = None


class FeeConfigUpdate(BaseModel):
    commission_rate: Optional[float] = None
    stamp_tax_rate: Optional[float] = None
    slippage: Optional[float] = None
    min_commission: Optional[float] = None


@router.get("", response_model=FeeConfigOut)
async def get_fee_config_route(_user: User = Depends(get_current_user)):
    """v_next: 完全走 sysconfig"""
    cfg = sysconfig.get_fee_dict(user="0")
    return FeeConfigOut(**cfg)


@router.patch("", response_model=FeeConfigOut, dependencies=[Depends(require_admin)])
async def update_fee_config(req: FeeConfigUpdate, user: User = Depends(get_current_user)):
    """v_next: 写 sysconfig.user='0' 默认 (set_value 已同步 cache+DB)"""
    if req.commission_rate is not None:
        sysconfig.set_value("0", "commission_rate", str(req.commission_rate),
                            "佣金费率 (万一)", user.username)
    if req.stamp_tax_rate is not None:
        sysconfig.set_value("0", "stamp_tax_rate", str(req.stamp_tax_rate),
                            "印花税率 (千一)", user.username)
    if req.slippage is not None:
        sysconfig.set_value("0", "slippage", str(req.slippage),
                            "滑点 (0.1%)", user.username)
    if req.min_commission is not None:
        sysconfig.set_value("0", "min_commission", str(req.min_commission),
                            "最低佣金 (元)", user.username)
    return FeeConfigOut(**sysconfig.get_fee_dict(user="0"))
