"""
admin/session.py — v_next 交易时段配置 (整合到 sysconfig)

GET   /api/admin/trading-session   读 trdtime (HHMMSS-HHMMSS;...)
PATCH /api/admin/trading-session   改 trdtime (admin only)
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.services.guards import require_admin
from server.services import sysconfig
from server.auth.deps import get_current_user
from server.tables import Row

router = APIRouter()


class SessionOut(BaseModel):
    trdtime: str
    is_half_day: bool


class SessionUpdate(BaseModel):
    trdtime: Optional[str] = None
    is_half_day: Optional[bool] = None


@router.get("", response_model=SessionOut)
async def get_session(_user: Row = Depends(get_current_user)):
    """v_next: 读 sysconfig.trdtime"""
    from server.repo.system import TradingClock
    win = TradingClock.get_session_window()
    return SessionOut(
        trdtime=sysconfig.get_trdtime_str(),
        is_half_day=win.get("is_half_day", False),
    )


@router.patch("", response_model=SessionOut, dependencies=[Depends(require_admin)])
async def update_session(req: SessionUpdate, user: Row = Depends(get_current_user)):
    """v_next: 写 sysconfig.trdtime (HHMMSS-HHMMSS;HHMMSS-HHMMSS)."""
    if req.trdtime is not None:
        # 验证格式合法
        parsed = sysconfig.parse_trdtime(req.trdtime)
        if not parsed:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"invalid trdtime format: {req.trdtime!r}")
        sysconfig.set_value("0", "trdtime", req.trdtime,
                            "交易时段 (分号分隔多段 HHMMSS-HHMMSS)", user.username)
        # 清缓存
        from server.repo.system import TradingClock
        TradingClock._loaded_at = None
    return await get_session(user)
