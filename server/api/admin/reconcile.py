"""
admin/reconcile.py

GET  /api/admin/reconcile/config      → 读对账配置
PATCH /api/admin/reconcile/config      → 改 auto_reconcile
GET  /api/admin/reconcile/reports      → 历史报告列表（90 天）
GET  /api/admin/reconcile/reports/{trd_date}/{mode}/{created_at} → 单个报告详情

- ReconcileReport 复合主键 (trd_date, mode, created_at)
- 复合主键查询走 server.tables.ReconcileReport.query_one(trd_date=..., mode=..., created_at=...)
- 范围查询 (created_at >= cutoff) 走 server.tables.get_conn() 原生 SQL（API 不支持范围）
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
import json

from server.db import get_db
from server.models.user import User
from server.services.guards import require_admin
from server.services import sysconfig
from server.utils.time import format_db_dt
from server.tables import ReconcileReport, get_conn, scalar_query
from sqlalchemy import text as _sa_text

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
    """id 字段为 created_at 时间戳（Report 复合主键含 created_at）"""
    created_at: str
    trd_date: str
    mode: str
    rpc_status: str


@router.get("/config", response_model=ReconcileConfigOut)
async def get_config(db: Session = Depends(get_db), _=Depends(require_admin)):
    """读 sysconfig cache (auto_reconcile + auto_use_broker_data)"""
    auto = sysconfig.get("auto_reconcile", False, user="0")
    broker = sysconfig.get("auto_use_broker_data", 1, user="0")
    if auto is None or broker is None:
        # cache miss (极少见, 未启动加载): 用默认
        auto, broker = False, 1
    return ReconcileConfigOut(
        auto_reconcile=bool(auto),
        auto_use_broker_data=int(broker),
        updated_by='init' if auto is None or broker is None else 'cache',
    )


@router.patch("/config", response_model=ReconcileConfigOut)
async def update_config(
    req: ReconcileConfigUpdate,
    admin_user: User = Depends(require_admin),
):
    """写 sysconfig.user='0'"""
    if req.auto_reconcile is not None:
        sysconfig.set_value("0", "auto_reconcile", "1" if req.auto_reconcile else "0",
                            "自动对账开关 (0=人工/1=自动)", admin_user.username)
    if req.auto_use_broker_data is not None:
        sysconfig.set_value("0", "auto_use_broker_data", "1" if req.auto_use_broker_data else "0",
                            "自动对账时以柜台为准 (0=本地/1=柜台)", admin_user.username)
    auto = sysconfig.get("auto_reconcile", False, user="0")
    broker = sysconfig.get("auto_use_broker_data", 1, user="0")
    return ReconcileConfigOut(
        auto_reconcile=bool(auto),
        auto_use_broker_data=int(broker),
        updated_by=admin_user.username,
    )


@router.get("/reports", response_model=List[ReconcileReportSummary])
async def list_reports(db: Session = Depends(get_db), _=Depends(require_admin)):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=REPORT_RETENTION_DAYS)
    # 走 tables 层 get_conn() 原生 SQL
    #   (ReconcileReport.query_by/query_by_fields 仅支持等值过滤, 不支持 created_at >= 范围)
    sql = (
        "SELECT created_at, trd_date, mode, rpc_status FROM `reconcile_report` "
        "WHERE created_at >= :cutoff ORDER BY created_at DESC LIMIT 200"
    )
    with get_conn() as conn:
        cur = conn.execute(_sa_text(sql), {"cutoff": cutoff})
        rows = cur.mappings().all()
    return [
        ReconcileReportSummary(
            created_at=format_db_dt(r["created_at"]) if r["created_at"] else "",
            trd_date=r["trd_date"], mode=r["mode"],
            rpc_status=r["rpc_status"],
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
    # 走 ReconcileReport.query_one (复合主键)
    r = ReconcileReport.query_one(trd_date=trd_date, mode=mode, created_at=ts)
    if not r:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"报告 {trd_date}/{mode}@{created_at} 不存在"})
    return {
        "created_at": format_db_dt(r["created_at"]) if r["created_at"] else None,
        "trd_date": r["trd_date"],
        "mode": r["mode"],
        "rpc_status": r["rpc_status"],
        "error_message": r["error_message"],
        "created_by": r["created_by"],
        "diffs": json.loads(r["diffs_json"]) if r["diffs_json"] else {},
    }
