"""
admin/sys_status.py — v_next 重构版（SysStatus 单行宽表）

交易日状态机写入 sys_status 表（替代 trading_day）。
URL 路径：/api/admin/sys-status（替代 /api/admin/trading-day）。

POST /api/admin/sys-status/init
  body: { "trd_date": "20260614", "mode": "auto" | "manual" }
  -> 触发对账 + 切交易日（UPDATE id=1 行的 trd_date）
  -> 失败返 503 + 报告 id

GET  /api/admin/sys-status/active
  -> 当前 SysStatus 行（id=1）

POST /api/admin/sys-status/reconcile
  body: { "trd_date": "20260614", "mode": "manual" }
  -> 仅生成对账报告（不切日）

v_next 改动（2026-07-22, 用户明令）:
- 表 sys_status 单行化（id=1, 强制 CHECK id=1）
- 字段 trd_date 不再是 PK；切日 = UPDATE 单行 trd_date
- 历史交易日从 reconcile_report.trd_date 查
- 删除 GET /api/admin/sys-status 列表端点（用户接受此损失）
"""
from fastapi import APIRouter, HTTPException, Depends
from server.api.deps import require_rpc_ok  # v101: RPC 健康统一 deps
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import asyncio

from server.db import get_db
from server.models.orm import SysStatus, get_active_sysstatus
from server.models.user import User
from server.services.reconcile import do_reconcile
from server.services.guards import require_admin
from server.utils.time import format_db_dt

router = APIRouter()


class SysStatusOut(BaseModel):
    """SysStatus 响应模型 — v_next 单行宽表

    字段名直接对齐前端 SystemInit.vue
    """
    trd_date: str
    status: str
    is_half_day: int = 0
    activated_at: Optional[str] = None
    activated_by: Optional[int] = None
    closed_at: Optional[str] = None
    closed_by: Optional[int] = None
    remark: str = ""
    updated_at: Optional[str] = None


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


@router.post("/init", response_model=InitResponse,
             dependencies=[Depends(require_rpc_ok)])  # v101: 切日前 RPC 健康
async def init_trading_day(
    req: InitRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """人工日初: 触发对账 + 切交易日（v_next 单行 UPSERT）"""
    if len(req.trd_date) != 8 or not req.trd_date.isdigit():
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_TRD_DATE", "msg": "trd_date 必须是 8 位数字字符串"}
        )

    # v101: RPC 健康检查已通过 Depends(require_rpc_ok) 在路由层拦截 (替换 v99 内联)

    by_user = str(admin_user.id)

    # v117: 切日前先读"前一交易日" — 后续 ws 推送 previous_trd_date 用
    #   SysStatus 单行表 id=1, UPDATE 前查到的 trd_date 即切日前的
    _previous_trd_date = None
    try:
        prev = db.query(SysStatus).filter(SysStatus.id == 1).first()
        _previous_trd_date = prev.trd_date if prev else None
    except Exception:
        _previous_trd_date = None

    # v118: 系统初始化走 init 路径 (覆盖 positions 表, 一次性同步 broker 持仓)
    result = await do_reconcile(db, req.trd_date, by_user, reconcile_kind='init')

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

    # 切日已写入 (do_reconcile 内 UPDATE id=1 行), 这里直接读出来
    row = get_active_sysstatus(db)

    # v25: 日初成功后 ws 推 system_status_change (v117), 让前端自动刷新 holdings/asset/position 缓存
    #   v117: 去掉 init_completed 类型, 合并到 system_update channel — type='system_status_change'
    #   payload 含 rpc_status 字段 + trd_date + previous_trd_date (切日轨迹)
    try:
        from server.ws.manager import ws_manager
        _init_status = 'partial' if result.get('error') else 'ok'
        _ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        asyncio.ensure_future(ws_manager.broadcast(
            'system_update',
            {
                'type': 'system_status_change',     # v117: 替换 init_completed
                'change_kind': 'init_completed',    # 保留旧语义供前端过渡用
                'trd_date': req.trd_date,           # v117: 交易日信息 (用户口径: 必须有)
                'previous_trd_date': _previous_trd_date,
                'status': _init_status,             # 'ok' / 'partial'
                # v117.1: 移除 rpc_status 字段 — 用户口径: rpc_status 仍独立走自己的 type='rpc_status' 路径
                'report_id': result['report_id'],
                'ts': _ts,
            },
            trace_id=f"init:{req.trd_date}:{result['report_id']}",
        ))
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning(
            "init_trading_day ws broadcast failed: %s", _e
        )

    return InitResponse(
        code=0,
        msg="日初完成",
        report_id=result['report_id'],
        applied=result['applied'],
        trading_day=SysStatusOut(
            trd_date=row.trd_date,
            status=row.status,
            is_half_day=row.is_half_day,
            activated_at=format_db_dt(row.initialized_at) if row.initialized_at else None,
            activated_by=int(row.initialized_by) if row.initialized_by else None,
            closed_at=format_db_dt(row.closed_at) if row.closed_at else None,
            closed_by=int(row.closed_by) if row.closed_by else None,
            remark=row.remark or "",
            updated_at=format_db_dt(row.updated_at) if row.updated_at else None,
        ) if row else None,
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
    # v118: manual reconcile 不动 positions (pos_push 已接管), 只生成报告
    result = await do_reconcile(db, req.trd_date, by_user, reconcile_kind='incremental')
    db.commit()
    return InitResponse(
        code=0 if result['ok'] else 1,
        msg=result['error'] or '对账失败' if not result['ok'] else 'manual reconcile ok',
        report_id=result['report_id'],
        applied=False,
        trading_day=None,
        error=result.get('error'),
    )


@router.get("/active", response_model=SysStatusOut)
async def get_active_trading_day(db: Session = Depends(get_db)):
    """获取当前 SysStatus 单行（id=1）

    无记录 → 返默认值占位 (status="closed", trd_date=""),
    避免前端 null 处理。
    """
    row = get_active_sysstatus(db)
    if not row:
        return SysStatusOut(
            trd_date="",
            status="closed",
        )
    return SysStatusOut(
        trd_date=row.trd_date,
        status=row.status,
        is_half_day=row.is_half_day,
        activated_at=format_db_dt(row.initialized_at) if row.initialized_at else None,
        activated_by=int(row.initialized_by) if row.initialized_by else None,
        closed_at=format_db_dt(row.closed_at) if row.closed_at else None,
        closed_by=int(row.closed_by) if row.closed_by else None,
        remark=row.remark or "",
        updated_at=format_db_dt(row.updated_at) if row.updated_at else None,
    )
