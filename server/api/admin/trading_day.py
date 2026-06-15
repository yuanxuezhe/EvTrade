"""
admin/trading_day.py — v4 日初处理（v6 字段名修正）

POST /api/admin/trading-day/init
  body: { "trd_date": "20260614", "mode": "auto" | "manual" }
  -> 触发对账 + 切交易日
  -> 失败返 503 + 报告 id

GET  /api/admin/trading-day
  -> 历史交易日列表（90 天）
GET  /api/admin/trading-day/active
  -> 当前激活的交易日
POST /api/admin/trading-day/reconcile
  body: { "trd_date": "20260614", "mode": "manual" }
  -> 仅生成对账报告（不切日）

v6 修复：
- TradingDayOut 字段名对齐前端 SystemInit.vue: trd_date / activated_at / activated_by
- 加 /reconcile 端点（前端"仅生成对账报告"按钮）
- InitRequest 改 trd_date（前端 admin.js 已用 trd_date）
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from db import get_db
from models.orm import TradingDay, ReconcileReport
from models.user import User
from services.reconcile import do_reconcile
from services.guards import require_admin

router = APIRouter()

REPORT_RETENTION_DAYS = 90


class TradingDayOut(BaseModel):
    """TradingDay 响应模型 — 字段名直接对齐前端 SystemInit.vue

    NOTE: ORM 字段 initialized_at/initialized_by, 这里取一个"语义更清晰"
    的命名 (activated_*) 直接暴露给前端, ORM 字段不再 alias 转换。
    """
    id: int
    trd_date: str
    status: str
    activated_at: Optional[str] = None
    last_reconcile_at: Optional[str] = None
    activated_by: str = ""


class InitRequest(BaseModel):
    trd_date: str  # 8 位数字字符串
    mode: str = "auto"  # auto | manual


class InitResponse(BaseModel):
    code: int = 0
    msg: str = ""
    report_id: Optional[int] = None
    applied: bool = False
    trading_day: Optional[TradingDayOut] = None
    error: Optional[str] = None


class ReconcileRequest(BaseModel):
    trd_date: str
    mode: str = "manual"


@router.post("/init", response_model=InitResponse)
async def init_trading_day(
    req: InitRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """人工日初: 触发对账 + 切交易日"""
    if len(req.trd_date) != 8 or not req.trd_date.isdigit():
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_TRD_DATE", "msg": "trd_date 必须是 8 位数字字符串"}
        )

    by_user = str(admin_user.id)

    result = await do_reconcile(db, req.trd_date, by_user)

    if not result['ok']:
        db.commit()
        return InitResponse(
            code=1,
            msg=result['error'] or '对账失败',
            report_id=result['report_id'],
            applied=False,
            trading_day=None,
            error=result['error'],
        )

    # upsert 已在 do_reconcile 完成, 这里直接查 active 行
    new_day = db.query(TradingDay).filter_by(
        status='active', current_date=req.trd_date
    ).first()
    return InitResponse(
        code=0,
        msg="日初完成",
        report_id=result['report_id'],
        applied=result['applied'],
        trading_day=TradingDayOut(
            id=new_day.id if new_day else 0,
            trd_date=req.trd_date,
            status='active',
            activated_at=new_day.initialized_at.isoformat() if new_day and new_day.initialized_at else None,
            activated_by=str(new_day.initialized_by) if new_day and new_day.initialized_by else "0",
        ),
        error=None,
    )


@router.post("/reconcile", response_model=InitResponse)
async def reconcile_only(
    req: ReconcileRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """仅生成对账报告 (manual 模式, 不切日)"""
    if len(req.trd_date) != 8 or not req.trd_date.isdigit():
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_TRD_DATE", "msg": "trd_date 必须是 8 位数字字符串"}
        )
    by_user = str(admin_user.id)
    result = await do_reconcile(db, req.trd_date, by_user)
    db.commit()
    return InitResponse(
        code=0 if result['ok'] else 1,
        msg=result.get('error') or '对账报告已生成',
        report_id=result['report_id'],
        applied=False,
        trading_day=None,
        error=result.get('error'),
    )


@router.get("", response_model=List[TradingDayOut])
async def list_trading_days(days: int = 90, db: Session = Depends(get_db)):
    """历史交易日列表"""
    rows = db.query(TradingDay).order_by(desc(TradingDay.current_date)).limit(days).all()
    return [
        TradingDayOut(
            id=r.id,
            trd_date=r.current_date,
            status=r.status,
            activated_at=r.initialized_at.isoformat() if r.initialized_at else None,
            activated_by=str(r.initialized_by) if r.initialized_by else "0",
        ) for r in rows
    ]


@router.get("/active", response_model=TradingDayOut)
async def get_active_trading_day(db: Session = Depends(get_db)):
    """获取当前激活的交易日

    无记录 → 返默认值占位 (status="none", trd_date="", id=0),
    避免前端 null 处理。
    """
    row = db.query(TradingDay).filter_by(status='active').first()
    if not row:
        return TradingDayOut(
            id=0,
            trd_date="",
            status="none",
            activated_at=None,
            activated_by="0",
        )
    return TradingDayOut(
        id=row.id,
        trd_date=row.current_date,
        status=row.status,
        activated_at=row.initialized_at.isoformat() if row.initialized_at else None,
        activated_by=str(row.initialized_by) if row.initialized_by else "0",
    )
