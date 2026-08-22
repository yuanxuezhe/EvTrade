"""
admin/sys_status.py — SysStatus 单行宽表

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

- 表 sys_status 单行化（id=1, 强制 CHECK id=1）
- 字段 trd_date 不再是 PK；切日 = UPDATE 单行 trd_date
- 历史交易日从 reconcile_report.trd_date 查
"""
from fastapi import APIRouter, HTTPException, Depends
from server.api.deps import require_rpc_ok  # RPC 健康统一 deps
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import asyncio

from server.db import get_db
from server.tables import SysStatus
from server.models.orm import get_active_sysstatus  # helper 内部已走 Tables API；保留 orm.py 直到 A.7
from server.models.user import User
from server.services.reconcile import do_reconcile
from server.services.guards import require_admin
from server.utils.time import format_db_dt

router = APIRouter()


class SysStatusOut(BaseModel):
    """SysStatus 响应模型 — 单行宽表

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


def _broadcast_init_change(change_kind, status, trd_date, previous_trd_date, report_id):
    """init 生命周期广播 (init_start / init_aborted / init_completed) — fire-and-forget, 不阻塞 HTTP

    change init-push-gate: 前端据此开关「初始化推送丢弃门」
      - init_start    → 开 gate (reconcile 期间丢弃 pos/ord/trd 洪峰)
      - init_aborted  → 关 gate (失败, 不切日)
      - init_completed → 关 gate (既有成功路径)
    """
    try:
        from server.ws.manager import ws_manager
        _ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        asyncio.ensure_future(ws_manager.broadcast(
            'system_update',
            {
                'type': 'system_status_change',
                'change_kind': change_kind,
                'trd_date': trd_date,
                'previous_trd_date': previous_trd_date,
                'status': status,
                'report_id': report_id,
                'ts': _ts,
            },
            trace_id=f"init:{trd_date}:{report_id or 'start'}:{change_kind}",
        ))
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning(
            "init_trading_day ws broadcast failed (%s): %s", change_kind, _e
        )


@router.post("/init", response_model=InitResponse,
             dependencies=[Depends(require_rpc_ok)])  # 切日前 RPC 健康
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

    # RPC 健康检查已通过 Depends(require_rpc_ok) 在路由层拦截

    by_user = str(admin_user.id)

    # 切日前先读"前一交易日" — 后续 ws 推送 previous_trd_date 用
    #   SysStatus 单行表 id=1, UPDATE 前查到的 trd_date 即切日前的
    _previous_trd_date = None
    try:
        prev = SysStatus.query_one(id=1)
        _previous_trd_date = prev.trd_date if prev else None
    except Exception:
        _previous_trd_date = None

    # change init-push-gate: init_start 广播 → 前端开「初始化推送丢弃门」
    #   reconcile 期间 broker 仍可能推 pos_push/ord_cfm/trd_cfm 洪峰, 前端据此丢弃 (不写状态/不刷屏)
    _broadcast_init_change('init_start', 'initializing', req.trd_date, _previous_trd_date, None)

    # change init-push-gate: init reconcile 期间**后端**抑制 pos_push (DB 写 + 广播)
    #   do_reconcile(init) 全表覆盖 positions 时, broker 并发 pos_push 逐条判"新增/变化"会广播洪峰;
    #   但 init 后前端 resetForNewDay RPC 全量拉权威数据, 窗口期 pos_push 冗余 → with 抑制
    #   incremental (manual reconcile) 不动 positions, 不抑制
    from server.services.push.pos import suppress_pos_push
    with suppress_pos_push():
        # 系统初始化走 init 路径 (覆盖 positions 表, 一次性同步 broker 持仓)
        result = await do_reconcile(db, req.trd_date, by_user, reconcile_kind='init')

    if not result['ok']:
        db.commit()
        # change init-push-gate: 失败补广播 init_aborted → 前端关 gate
        #   (原失败路径无广播, 若缺失前端门会一直开, 推送被永久丢弃)
        _broadcast_init_change('init_aborted', 'error', req.trd_date, _previous_trd_date, result['report_id'])
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

    # 日初成功后 ws 推 system_status_change, 让前端自动刷新 holdings/asset/position 缓存
    #   合并到 system_update channel — type='system_status_change'
    #   不含 rpc_status 字段 — rpc_status 仍独立走自己的 type='rpc_status' 路径
    #   change init-push-gate: 走共享 helper _broadcast_init_change (init_completed → 前端关 gate)
    _init_status = 'partial' if result.get('error') else 'ok'
    _broadcast_init_change('init_completed', _init_status, req.trd_date, _previous_trd_date, result['report_id'])

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
    # manual reconcile 不动 positions (pos_push 已接管), 只生成报告
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
