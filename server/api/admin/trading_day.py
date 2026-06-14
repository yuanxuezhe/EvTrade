"""
admin/trading_day.py — v4 日初处理

POST /api/admin/trading-day/init
  body: { "TRD_DATE": "20260614" }
  → 触发对账 + 切交易日
  → 失败返 503 + 报告 id

GET /api/admin/trading-day
  → 当前激活的交易日 + 历史 90 天
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from db import get_db
from models.orm import TradingDay, ReconcileReport
from models.user import User
from services.reconcile import do_reconcile
from services.guards import require_admin

router = APIRouter()

# 对账报告保留天数
REPORT_RETENTION_DAYS = 90


class InitRequest(BaseModel):
    TRD_DATE: str  # 8 位数字字符串


class TradingDayOut(BaseModel):
    id: int
    current_date: str
    status: str
    initialized_at: Optional[str] = None
    initialized_by: str


class InitResponse(BaseModel):
    code: int = 0
    msg: str = ""
    report_id: Optional[int] = None
    applied: bool = False
    trading_day: Optional[TradingDayOut] = None
    error: Optional[str] = None


@router.post("/init", response_model=InitResponse,
             dependencies=[Depends(require_admin)])
async def init_trading_day(req: InitRequest, db: Session = Depends(get_db)):
    """人工日初：触发对账 + 切交易日"""
    if len(req.TRD_DATE) != 8 or not req.TRD_DATE.isdigit():
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_TRD_DATE", "msg": "TRD_DATE 必须是 8 位数字字符串"}
        )

    # 当前用户（admin 屏障已校验过）
    from auth.deps import get_current_user
    # 这里简化：通过 Depends 拿不到 user，改为从 require_admin 返回
    # 实际拿法：import get_current_user 单独注入
    # (FastAPI Depends 链调用方式：写在 dependencies 里时无法直接拿返回值)
    by_user = "admin"  # TODO: 改进获取用户名

    result = await do_reconcile(db, req.TRD_DATE, by_user)

    if not result['ok']:
        db.commit()
        return InitResponse(
            code=1,  # 1 = 对账失败
            msg=result['error'] or '对账失败',
            report_id=result['report_id'],
            applied=False,
            trading_day=None,
            error=result['error'],
        )

    new_day = db.query(TradingDay).filter_by(
        current_date=req.TRD_DATE, status='active'
    ).first()
    return InitResponse(
        code=0,
        msg="日初完成",
        report_id=result['report_id'],
        applied=result['applied'],
        trading_day=TradingDayOut(
            id=new_day.id if new_day else 0,
            current_date=req.TRD_DATE,
            status='active',
            initialized_at=new_day.initialized_at.isoformat() if new_day and new_day.initialized_at else None,
            initialized_by=by_user,
        ),
        error=None,
    )


@router.get("", response_model=List[TradingDayOut])
async def list_trading_days(days: int = 90, db: Session = Depends(get_db)):
    """历史交易日列表（默认 90 天）"""
    rows = db.query(TradingDay).order_by(desc(TradingDay.current_date)).limit(days).all()
    return [
        TradingDayOut(
            id=r.id,
            current_date=r.current_date,
            status=r.status,
            initialized_at=r.initialized_at.isoformat() if r.initialized_at else None,
            initialized_by=r.initialized_by or "",
        ) for r in rows
    ]


@router.get("/active", response_model=Optional[TradingDayOut])
async def get_active_trading_day(db: Session = Depends(get_db)):
    """获取当前激活的交易日"""
    row = db.query(TradingDay).filter_by(status='active').first()
    if not row:
        return None
    return TradingDayOut(
        id=row.id,
        current_date=row.current_date,
        status=row.status,
        initialized_at=row.initialized_at.isoformat() if row.initialized_at else None,
        initialized_by=row.initialized_by or "",
    )
