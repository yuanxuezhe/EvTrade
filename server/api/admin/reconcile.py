"""
admin/reconcile.py — v4 对账配置 + 历史报告

GET  /api/admin/reconcile/config      → 读对账配置
PATCH /api/admin/reconcile/config      → 改 auto_reconcile
GET  /api/admin/reconcile/reports      → 历史报告列表（90 天）
GET  /api/admin/reconcile/reports/{id} → 单个报告详情
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
import json

from db import get_db
from models.orm import ReconcileConfig, ReconcileReport
from models.user import User
from services.guards import require_admin

router = APIRouter()

REPORT_RETENTION_DAYS = 90


class ReconcileConfigOut(BaseModel):
    # ORM 存 int 0/1；前端 <el-switch> 期望 bool，<el-radio> 期望 int 0/1
    # 所以两个字段分别用不同类型序列化：
    auto_reconcile: bool          # switch 用
    auto_use_broker_data: int     # radio 用（不要转 bool，否则 :value="1" 匹配不上）
    updated_at: Optional[str] = None
    updated_by: str


class ReconcileConfigUpdate(BaseModel):
    auto_reconcile: Optional[bool] = None
    auto_use_broker_data: Optional[int] = None


class ReconcileReportSummary(BaseModel):
    id: int
    TRD_DATE: str
    mode: str
    rpc_status: str
    created_at: Optional[str] = None


@router.get("/config", response_model=ReconcileConfigOut)
async def get_config(db: Session = Depends(get_db), _=Depends(require_admin)):
    cfg = db.query(ReconcileConfig).first()
    if not cfg:
        cfg = ReconcileConfig(auto_reconcile=False, updated_by='init')
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return ReconcileConfigOut(
        auto_reconcile=bool(cfg.auto_reconcile),
        auto_use_broker_data=int(cfg.auto_use_broker_data),
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
        updated_by=cfg.updated_by or 'init',
    )


@router.patch("/config", response_model=ReconcileConfigOut)
async def update_config(
    req: ReconcileConfigUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    cfg = db.query(ReconcileConfig).first()
    if not cfg:
        cfg = ReconcileConfig()
        db.add(cfg)
    if req.auto_reconcile is not None:
        cfg.auto_reconcile = 1 if req.auto_reconcile else 0
    if req.auto_use_broker_data is not None:
        cfg.auto_use_broker_data = 1 if req.auto_use_broker_data else 0
    cfg.updated_by = str(admin_user.id)
    cfg.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cfg)
    return ReconcileConfigOut(
        auto_reconcile=bool(cfg.auto_reconcile),
        auto_use_broker_data=int(cfg.auto_use_broker_data),
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
        updated_by=cfg.updated_by,
    )


@router.get("/reports", response_model=List[ReconcileReportSummary])
async def list_reports(db: Session = Depends(get_db), _=Depends(require_admin)):
    cutoff = datetime.utcnow() - timedelta(days=REPORT_RETENTION_DAYS)
    rows = db.query(ReconcileReport).filter(
        ReconcileReport.created_at >= cutoff
    ).order_by(desc(ReconcileReport.created_at)).limit(200).all()
    return [
        ReconcileReportSummary(
            id=r.id, TRD_DATE=r.TRD_DATE, mode=r.mode,
            rpc_status=r.rpc_status,
            created_at=r.created_at.isoformat() if r.created_at else None,
        ) for r in rows
    ]


@router.get("/reports/{report_id}")
async def get_report(report_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    r = db.query(ReconcileReport).filter_by(id=report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"报告 {report_id} 不存在"})
    return {
        "id": r.id,
        "TRD_DATE": r.TRD_DATE,
        "mode": r.mode,
        "rpc_status": r.rpc_status,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "diffs": json.loads(r.diffs_json) if r.diffs_json else {},
    }
