"""
server/api/script_strategy/tasks.py — 任务端点 (v123)

REST 端点 (前缀 /api/script-strategy):
  GET    /tasks                  list (可按 strategy_id 过滤)
  GET    /tasks/{id}             detail
  POST   /tasks/{id}/stop        stop
  DELETE /tasks/{id}             delete
  GET    /tasks/{id}/logs        running logs
  GET    /tasks/{id}/signals     信号流 + 进度时间轴
  GET    /tasks/{id}/audit       永久 audit

v123: 任务创建统一走 /strategies/{id}/backtest (single/sweep) (v125 纯回测, /live 已删),
不再有 POST /tasks 与 /tasks/{id}/run(/run-sweep)。
脚本端点见 scripts.py; 策略/回测见 strategies.py。
"""
import logging
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from server.auth.deps import get_current_user
from server.models.user import User
from server.services import script_strategy as svc
from server.api.script_strategy.schemas import TaskOut

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/tasks", response_model=List[TaskOut])
def list_tasks_endpoint(
    status_filter: Optional[str] = Query(None, alias="status"),
    mode_filter: Optional[str] = Query(None, alias="mode"),
    strategy_id: Optional[int] = Query(None, description="v123: 限定策略 ID"),
    limit: int = Query(50, ge=1, le=200, description="最大返回数 (默认 50, 上限 200)"),
    user: User = Depends(get_current_user),
):
    """列 task

    v123 filter:
    - strategy_id: 限定策略
    - limit: 默认 50, 上限 200
    """
    return svc.list_tasks(
        user.id, user.role == "admin",
        status=status_filter, mode=mode_filter,
        strategy_id=strategy_id,
        limit=limit,
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    out = svc.get_task(task_id, user.id, user.role == "admin")
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


@router.post("/tasks/{task_id}/stop")
async def stop_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    """停止任务 (v120+: 转发到 strategy_exec)"""
    from datetime import datetime

    from server.config import settings
    from server.tables import StrategyTask

    row = StrategyTask.query_one(id=task_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    if user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}/internal/stop-task",
                headers={"X-Internal-Token": settings.STRATEGY_EXEC_API_TOKEN},
                json={"task_id": task_id},
            )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
        if response.status_code >= 400:
            log.warning("[stop_task] strategy_exec returned %d: %s",
                        response.status_code, response.text)
        return {"ok": True, "task_id": task_id}
    except httpx.RequestError as e:
        log.exception("[stop_task] forward failed")
        # 兜底: 直接标 stopped (即使 strategy_exec 不可达, task 状态也能在本地改)
        task_data = row._data
        task_data["status"] = "stopped"
        task_data["finished_at"] = datetime.now()
        row.update()
        return {"ok": True, "task_id": task_id, "fallback": True}


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    ok = svc.delete_task(task_id, user.id, user.role == "admin")
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return None


@router.get("/tasks/{task_id}/logs")
def get_task_logs_endpoint(task_id: int, user: User = Depends(get_current_user)):
    out = svc.get_task_logs(task_id, user.id, user.role == "admin")
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


@router.get("/tasks/{task_id}/signals")
def get_task_signals_endpoint(
    task_id: int,
    type_filter: Optional[str] = Query(None, alias="type", description="BUY/SELL/INFO/WARN"),
    limit: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
):
    """返任务的信号流 + 进度时间轴

    回测模式: 从 backtest_result.signal_log 返
    v125 纯回测后 live_signals 为遗留读路径 (仅存量实盘任务)
    """
    out = svc.get_task_signals(task_id, user.id, user.role == "admin",
                                type_filter=type_filter, limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


@router.get("/tasks/{task_id}/audit")
def get_task_audit_endpoint(
    task_id: int,
    trigger_type: Optional[str] = Query(None, description="BUY/SELL/INFO/..."),
    trd_date: Optional[str] = Query(None, description="YYYYMMDD"),
    limit: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
):
    """返 task 永久 audit (从 strategy_script_audit 表)

    📌 与 /signals 区别:
    - /signals: 限 500 条, 实时 in-memory
    - /audit:  永久存 DB, 支持按 trd_date / trigger_type 过滤, 量级无上限
    """
    out = svc.get_task_audit(task_id, user.id, user.role == "admin",
                              trigger_type=trigger_type, trd_date=trd_date, limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


__all__ = ["router"]
