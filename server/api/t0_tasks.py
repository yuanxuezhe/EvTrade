"""
t0_tasks.py — T0Task REST API (REQ-TRADE-014 + 018)

端点 (8 个)：
- POST   /api/t0-tasks              创建
- GET    /api/t0-tasks              列表 (?status=&stock_code=&days=)
- GET    /api/t0-tasks/overview     整体做T收益 (cross-task summary)
- GET    /api/t0-tasks/by-stock     单券做T收益 (per-stock)
- GET    /api/t0-tasks/{id}         详情
- PATCH  /api/t0-tasks/{id}         改 note / coefficient / target_volume / status
- DELETE /api/t0-tasks/{id}         仅 archived 可删
- POST   /api/t0-tasks/{id}/balance 一键配平
- POST   /api/t0-tasks/{id}/close   关任务 (强制配平到 base_volume)
- POST   /api/t0-tasks/{id}/archive 归档 (closed → archived)
- GET    /api/t0-tasks/{id}/stats   完整统计

RBAC：
- trader 可看/管自己的 task (user_id 过滤)
- admin 看所有 + 可强制管
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth.deps import get_current_user, require_admin, require_trader
from server.db import get_db
from server.models.user import User
from server.services.t0 import tasks as t0_tasks_service

log = logging.getLogger(__name__)

router = APIRouter()


# ──────── Schemas ────────

class CreateTaskRequest(BaseModel):
    stock_code: str = Field(..., min_length=6, max_length=16)
    base_volume: int = Field(0, ge=0, description="底仓量 (>= 0)")
    target_volume: int = Field(0, description="目标开仓量 (可为负数=净减仓)")
    coefficient: float = Field(1.0, ge=0.0, le=10.0)
    note: Optional[str] = Field(None, max_length=255)


class UpdateTaskRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=255)
    coefficient: Optional[float] = Field(None, ge=0.0, le=10.0)
    target_volume: Optional[int] = None
    status: Optional[str] = Field(None, pattern="^(active|closed)$")


class TaskSummary(BaseModel):
    task_net_volume: int
    position_vol: int
    realized_pnl: float
    unrealized_pnl: float
    trading_days: int
    win_rate: float


class TaskOut(BaseModel):
    id: int
    user_id: int
    stock_code: str
    base_volume: int
    target_volume: int
    coefficient: float
    status: str
    note: Optional[str]
    created_trd_date: str
    created_at: Optional[str] = None
    closed_at: Optional[str] = None
    summary: Optional[TaskSummary] = None


class BalanceResponse(BaseModel):
    action: str
    volume: int
    direction_volume: int
    price: float
    reason: str
    task_target_position: int
    current_position_vol: int
    task_net_volume: int


class CloseResponse(BaseModel):
    task: TaskOut
    balance_result: BalanceResponse


class OverviewResponse(BaseModel):
    active_task_count: int
    closed_task_count: int
    archived_task_count: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_commission: float
    total_stamp_tax: float
    avg_win_rate: float
    total_trading_days: int


class ByStockOut(BaseModel):
    stock_code: str
    realized_pnl: float
    unrealized_pnl: float
    net_volume: int
    task_count: int
    trading_days: int


class TaskStatsOut(BaseModel):
    task: dict
    summary: dict
    daily: List[dict]


class GlobalStatsResponse(BaseModel):
    """v18: 全局 stats (admin only) - 跨用户/跨 task 聚合"""
    summary: dict        # {active_task_count, closed_task_count, total_realized_pnl, ...}
    by_stock: List[dict] # [{stock_code, realized_pnl, net_volume, task_count}]
    daily: List[dict]    # [{trd_date, realized_pnl, commission, stamp_tax}]


# ──────── Helpers ────────

def _user_is_admin(user: User) -> bool:
    return user.role == "admin"


def _is_trader_or_admin(user: User) -> bool:
    return user.role in ("trader", "admin")


# ──────── Endpoints ────────

@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    req: CreateTaskRequest,
    user: User = Depends(require_trader),
    db: Session = Depends(get_db),
):
    """创建 T0Task. trader/admin 可用."""
    try:
        task = t0_tasks_service.create_task(
            db, user_id=user.id, stock_code=req.stock_code,
            base_volume=req.base_volume, target_volume=req.target_volume,
            coefficient=req.coefficient, note=req.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    summary = t0_tasks_service._compute_summary(db, task)
    return TaskOut(
        id=task.id, user_id=task.user_id, stock_code=task.stock_code,
        base_volume=task.base_volume, target_volume=task.target_volume,
        coefficient=task.coefficient, status=task.status,
        note=task.note, created_trd_date=task.created_trd_date,
        created_at=task.created_at.isoformat() if task.created_at else None,
        closed_at=task.closed_at.isoformat() if task.closed_at else None,
        summary=TaskSummary(**summary),
    )


@router.get("", response_model=List[TaskOut])
async def list_tasks(
    status: Optional[str] = Query(None, pattern="^(active|closed|archived)$"),
    stock_code: Optional[str] = None,
    days: Optional[int] = Query(None, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列表 task. trader 仅看自己; admin 看所有."""
    rows = t0_tasks_service.list_tasks(
        db, user_id=user.id, is_admin=_user_is_admin(user),
        status=status, stock_code=stock_code, days=days,
    )
    out = []
    for r in rows:
        s = {
            'task_net_volume': r.pop('task_net_volume'),
            'position_vol': r.pop('position_vol'),
            'realized_pnl': r.pop('realized_pnl'),
            'unrealized_pnl': r.pop('unrealized_pnl'),
            'trading_days': r.pop('trading_days'),
            'win_rate': r.pop('win_rate'),
        }
        _created_at = r.pop('created_at', None)
        _closed_at = r.pop('closed_at', None)
        out.append(TaskOut(
            **r,
            created_at=_created_at.isoformat() if _created_at else None,
            closed_at=_closed_at.isoformat() if _closed_at else None,
            summary=TaskSummary(**s),
        ))
    return out


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """整体做T收益 (cross-task summary)."""
    o = t0_tasks_service.list_overview(
        db, user_id=user.id, is_admin=_user_is_admin(user),
    )
    return OverviewResponse(**o)


@router.get("/stats", response_model=GlobalStatsResponse)
async def get_global_stats(
    user: User = Depends(require_admin),  # v18: 全局 stats 仅 admin 可见
    db: Session = Depends(get_db),
):
    """全局 stats (all users + 跨期). admin only.

    必放在 '/{task_id}' 前 — FastAPI 路由按声明顺序匹配, 否则会被吃成 task_id='stats'。

    daily 字段: 跨 task 跨日明细聚合成本高 (N×M) — v18 暂留空 list,
    v19 可补 SQL GROUP BY trd_date 优化。
    """
    o = t0_tasks_service.list_overview(db, user_id=user.id, is_admin=True)
    bs = t0_tasks_service.list_overview_by_stock(db, user_id=user.id, is_admin=True)
    return GlobalStatsResponse(
        summary={
            'active_task_count': o['active_task_count'],
            'closed_task_count': o['closed_task_count'],
            'archived_task_count': o['archived_task_count'],
            'total_realized_pnl': o['total_realized_pnl'],
            'total_unrealized_pnl': o['total_unrealized_pnl'],
            'total_commission': o['total_commission'],
            'total_stamp_tax': o['total_stamp_tax'],
            'avg_win_rate': o['avg_win_rate'],
            'total_trading_days': o['total_trading_days'],
        },
        by_stock=bs,
        daily=[],  # 跨 task 跨日聚合 v19 补
    )


@router.get("/by-stock", response_model=List[ByStockOut])
async def get_by_stock(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单券做T收益 (per-stock)."""
    bs = t0_tasks_service.list_overview_by_stock(
        db, user_id=user.id, is_admin=_user_is_admin(user),
    )
    return [ByStockOut(**row) for row in bs]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = t0_tasks_service.get_task_detail(
        db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
    )
    if not d:
        raise HTTPException(status_code=404, detail="task 不存在或无权访问")

    s = {
        'task_net_volume': d.pop('task_net_volume'),
        'position_vol': d.pop('position_vol'),
        'realized_pnl': d.pop('realized_pnl'),
        'unrealized_pnl': d.pop('unrealized_pnl'),
        'trading_days': d.pop('trading_days'),
        'win_rate': d.pop('win_rate'),
    }
    _created_at = d.pop('created_at', None)
    _closed_at = d.pop('closed_at', None)
    return TaskOut(
        **d,
        created_at=_created_at.isoformat() if _created_at else None,
        closed_at=_closed_at.isoformat() if _closed_at else None,
        summary=TaskSummary(**s),
    )


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    req: UpdateTaskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        t = t0_tasks_service.update_task(
            db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
            note=req.note, coefficient=req.coefficient,
            target_volume=req.target_volume, status=req.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not t:
        raise HTTPException(status_code=404, detail="task 不存在或无权访问")

    summary = t0_tasks_service._compute_summary(db, t)
    return TaskOut(
        id=t.id, user_id=t.user_id, stock_code=t.stock_code,
        base_volume=t.base_volume, target_volume=t.target_volume,
        coefficient=t.coefficient, status=t.status,
        note=t.note, created_trd_date=t.created_trd_date,
        created_at=t.created_at.isoformat() if t.created_at else None,
        closed_at=t.closed_at.isoformat() if t.closed_at else None,
        summary=TaskSummary(**summary),
    )


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除 task. 仅 archived 状态可删."""
    try:
        ok = t0_tasks_service.delete_task(
            db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="task 不存在或无权访问")
    return {"success": True, "deleted": task_id}


@router.post("/{task_id}/balance", response_model=BalanceResponse)
async def balance_task(
    task_id: int,
    user: User = Depends(require_trader),
    db: Session = Depends(get_db),
):
    """一键配平 (按 task 净敞口 - base_volume)."""
    try:
        r = t0_tasks_service.balance_task(
            db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if r.get('action') == 'NONE' and r.get('volume') == 0:
        # task 不存在 / 状态不允许
        detail = r.get('reason', 'task 不允许配平')
        raise HTTPException(status_code=400, detail=detail)
    return BalanceResponse(**r)


@router.post("/{task_id}/close", response_model=CloseResponse)
async def close_task(
    task_id: int,
    user: User = Depends(require_trader),
    db: Session = Depends(get_db),
):
    """关 task (强制配平到 base_volume 后改 status=closed)."""
    try:
        c = t0_tasks_service.close_task(
            db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    task_dict = c['task']
    summary = t0_tasks_service._compute_summary(db, type('T', (), task_dict)())
    _created_at = task_dict.pop('created_at', None)
    _closed_at = task_dict.pop('closed_at', None)
    return CloseResponse(
        task=TaskOut(
            **task_dict,
            created_at=_created_at.isoformat() if _created_at else None,
            closed_at=_closed_at.isoformat() if _closed_at else None,
            summary=TaskSummary(**summary),
        ),
        balance_result=BalanceResponse(**c['balance_result']),
    )


@router.post("/{task_id}/archive")
async def archive_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """归档 (closed → archived)."""
    try:
        t = t0_tasks_service.archive_task(
            db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not t:
        raise HTTPException(status_code=404, detail="task 不存在或无权访问")
    return {"success": True, "id": t.id, "status": t.status}


@router.get("/{task_id}/stats", response_model=TaskStatsOut)
async def get_task_stats(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """task 完整统计 (realized + unrealized + win_rate + trading_days + daily[])."""
    # 先鉴权 (admin 看所有; trader 仅自己)
    t_check = t0_tasks_service.get_task_detail(
        db, task_id=task_id, user_id=user.id, is_admin=_user_is_admin(user),
    )
    if not t_check:
        raise HTTPException(status_code=404, detail="task 不存在或无权访问")

    s = t0_tasks_service.aggregate_task_stats(db, task_id=task_id)
    if not s:
        raise HTTPException(status_code=404, detail="task 不存在")
    return TaskStatsOut(**s)