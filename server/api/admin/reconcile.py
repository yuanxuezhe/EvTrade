"""
admin/reconcile.py — v5 重构版（schema refactor）

GET  /api/admin/reconcile/config      → 读对账配置
PATCH /api/admin/reconcile/config      → 改 auto_reconcile
GET  /api/admin/reconcile/reports      → 历史报告列表（90 天）
GET  /api/admin/reconcile/reports/{trd_date}/{mode}/{created_at} → 单个报告详情

v5 改动：
- ReconcileReport 复合主键 (trd_date, mode, created_at)
- 响应中 id 字段改为 created_at 时间戳
- TRD_DATE → trd_date
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
import json

from server.db import get_db
from server.models.orm import ReconcileConfig, ReconcileReport
from server.models.user import User
from server.services.guards import require_admin
from server.services import sysconfig
from server.utils.time import format_db_dt

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
    """v5: id 字段改为 created_at 时间戳（Report 复合主键含 created_at）"""
    created_at: str
    trd_date: str
    mode: str
    rpc_status: str


@router.get("/config", response_model=ReconcileConfigOut)
async def get_config(db: Session = Depends(get_db), _=Depends(require_admin)):
    """v78: 优先读 sysconfig cache, cache miss 回退旧 ReconcileConfig 表"""
    auto = sysconfig.get("auto_reconcile", False, user="0")
    broker = sysconfig.get("auto_use_broker_data", 1, user="0")
    if auto is None and broker is None:
        # cache miss 全 None (未加载), 回退旧表
        cfg = db.query(ReconcileConfig).first()
        if cfg:
            return ReconcileConfigOut(
                auto_reconcile=bool(cfg.auto_reconcile),
                auto_use_broker_data=int(cfg.auto_use_broker_data),
                updated_at=format_db_dt(cfg.updated_at) if cfg.updated_at else None,
                updated_by=str(cfg.updated_by) if cfg.updated_by is not None else 'init',
            )
        auto, broker = False, 1
    return ReconcileConfigOut(
        auto_reconcile=bool(auto),
        auto_use_broker_data=int(broker),
    )


@router.patch("/config", response_model=ReconcileConfigOut)
async def update_config(
    req: ReconcileConfigUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """v78: 写 sysconfig.user='0' + 同步旧 ReconcileConfig 表"""
    if req.auto_reconcile is not None:
        sysconfig.set_value("0", "auto_reconcile", "1" if req.auto_reconcile else "0",
                            "自动对账开关 (0=人工/1=自动)", admin_user.username)
    if req.auto_use_broker_data is not None:
        sysconfig.set_value("0", "auto_use_broker_data", "1" if req.auto_use_broker_data else "0",
                            "自动对账时以柜台为准 (0=本地/1=柜台)", admin_user.username)
    # 同步旧表 (向后兼容)
    cfg = db.query(ReconcileConfig).first()
    if not cfg:
        cfg = ReconcileConfig()
        db.add(cfg)
    cfg.auto_reconcile = int(sysconfig.get("auto_reconcile", False, user="0"))
    cfg.auto_use_broker_data = int(sysconfig.get("auto_use_broker_data", 1, user="0"))
    cfg.updated_by = admin_user.id
    cfg.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(cfg)
    return ReconcileConfigOut(
        auto_reconcile=bool(cfg.auto_reconcile),
        auto_use_broker_data=int(cfg.auto_use_broker_data),
        updated_at=format_db_dt(cfg.updated_at) if cfg.updated_at else None,
        updated_by=str(cfg.updated_by) if cfg.updated_by is not None else '',
    )


@router.get("/reports", response_model=List[ReconcileReportSummary])
async def list_reports(db: Session = Depends(get_db), _=Depends(require_admin)):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=REPORT_RETENTION_DAYS)
    rows = db.query(ReconcileReport).filter(
        ReconcileReport.created_at >= cutoff
    ).order_by(desc(ReconcileReport.created_at)).limit(200).all()
    return [
        ReconcileReportSummary(
            created_at=format_db_dt(r.created_at) if r.created_at else "",
            trd_date=r.trd_date, mode=r.mode,
            rpc_status=r.rpc_status,
        ) for r in rows
    ]


@router.get("/reports/{trd_date}/{mode}/{created_at}")
async def get_report(
    trd_date: str, mode: str, created_at: str,
    db: Session = Depends(get_db), _=Depends(require_admin),
):
    """按复合主键 (trd_date, mode, created_at) 查单个报告"""
    # Python 3.6 兼容: 用 strptime 代替 fromisoformat (3.7+)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            ts = datetime.strptime(created_at, fmt)
            break
        except ValueError:
            continue
    else:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_CREATED_AT", "msg": f"created_at 解析失败: {created_at}"}
        )
    r = db.query(ReconcileReport).filter_by(
        trd_date=trd_date, mode=mode, created_at=ts
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"报告 {trd_date}/{mode}@{created_at} 不存在"})
    return {
        "created_at": format_db_dt(r.created_at) if r.created_at else None,
        "trd_date": r.trd_date,
        "mode": r.mode,
        "rpc_status": r.rpc_status,
        "error_message": r.error_message,
        "created_by": r.created_by,
        "diffs": json.loads(r.diffs_json) if r.diffs_json else {},
    }
