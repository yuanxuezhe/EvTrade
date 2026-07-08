"""
admin/sys_status.py — v5 重构版（schema refactor）

原 admin/trading_day.py 重命名。交易日状态机写入 sys_status 表（替代 trading_day）。
URL 路径：/api/admin/sys-status（替代 /api/admin/trading-day）。

POST /api/admin/sys-status/init
  body: { "trd_date": "20260614", "mode": "auto" | "manual" }
  -> 触发对账 + 切交易日
  -> 失败返 503 + 报告 id

GET  /api/admin/sys-status
  -> 历史交易日列表（90 天）
GET  /api/admin/sys-status/active
  -> 当前激活的交易日
POST /api/admin/sys-status/reconcile
  body: { "trd_date": "20260614", "mode": "manual" }
  -> 仅生成对账报告（不切日）

v5 改动：
- 表 trading_day → sys_status；类 TradingDay → SysStatus
- 字段 current_date → trd_date
- 复合主键 → trd_date 单 PK（无 id）
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from server.db import get_db
from server.models.orm import SysStatus
from server.models.user import User
from server.services.reconcile import do_reconcile
from server.services.guards import require_admin
from server.utils.time import format_db_dt

router = APIRouter()

REPORT_RETENTION_DAYS = 90


class SysStatusOut(BaseModel):
    """SysStatus 响应模型 — 字段名直接对齐前端 SystemInit.vue

    v5: 移除 id（trd_date 即 PK）
    """
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
    trading_day: Optional[SysStatusOut] = None
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
    new_day = db.query(SysStatus).filter_by(
        status='active', trd_date=req.trd_date
    ).first()
    return InitResponse(
        code=0,
        msg="日初完成",
        report_id=result['report_id'],
        applied=result['applied'],
        trading_day=SysStatusOut(
            trd_date=req.trd_date,
            status='active',
            activated_at=format_db_dt(new_day.initialized_at) if new_day and new_day.initialized_at else None,
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


@router.get("", response_model=List[SysStatusOut])
async def list_trading_days(days: int = 90, db: Session = Depends(get_db)):
    """历史交易日列表"""
    rows = db.query(SysStatus).order_by(desc(SysStatus.trd_date)).limit(days).all()
    return [
        SysStatusOut(
            trd_date=r.trd_date,
            status=r.status,
            activated_at=format_db_dt(r.initialized_at) if r.initialized_at else None,
            activated_by=str(r.initialized_by) if r.initialized_by else "0",
        ) for r in rows
    ]


@router.get("/active", response_model=SysStatusOut)
async def get_active_trading_day(db: Session = Depends(get_db)):
    """获取当前激活的交易日

    无记录 → 返默认值占位 (status="none", trd_date=""),
    避免前端 null 处理。
    """
    row = db.query(SysStatus).filter_by(status='active').first()
    if not row:
        return SysStatusOut(
            trd_date="",
            status="none",
            activated_at=None,
            activated_by="0",
        )
    return SysStatusOut(
        trd_date=row.trd_date,
        status=row.status,
        activated_at=format_db_dt(row.initialized_at) if row.initialized_at else None,
        activated_by=str(row.initialized_by) if row.initialized_by else "0",
    )
