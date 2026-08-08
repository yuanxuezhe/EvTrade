"""
strategy_exec.api.internal — 4 internal endpoint (Phase 1 mock)

Phase 1: 仅返 mock JSON, 不真正执行
Phase 2: 加 Backtrader 引擎调用
Phase 3: EvTrade 转发调这里

所有 endpoint 需校验 X-Internal-Token (env STRATEGY_EXEC_API_TOKEN)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from strategy_exec.config import get_settings


router = APIRouter(prefix="/internal", tags=["internal"])


# ──────────── 鉴权依赖 ────────────


async def verify_internal_token(x_internal_token: Optional[str] = Header(None)) -> None:
    """校验 X-Internal-Token 与 STRATEGY_EXEC_API_TOKEN 一致

    401 if missing or invalid (防 EvTrade 之外的客户端误调)
    """
    settings = get_settings()
    if x_internal_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_TOKEN", "msg": "X-Internal-Token header required"},
        )
    if x_internal_token != settings.strategy_exec_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "msg": "invalid X-Internal-Token"},
        )


# ──────────── Pydantic schemas ────────────


class RunTaskRequest(BaseModel):
    task_id: int = Field(ge=1)
    user_id: int = Field(ge=0)
    script_id: str = Field(min_length=1, max_length=64)
    stock_code: str = Field(min_length=1, max_length=16)
    mode: str = Field(pattern="^(backtest|live)$")
    params: dict = Field(default_factory=dict)
    # 回测专属
    backtest_start_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    backtest_end_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    period: Optional[str] = Field(default=None, pattern=r"^(1d|1m|5m|15m|30m|60m)$")
    fields: Optional[str] = Field(default=None)


class RunTaskResponse(BaseModel):
    task_id: int
    status: str  # "accepted"
    msg: str


class StopTaskRequest(BaseModel):
    task_id: int = Field(ge=1)


class StopTaskResponse(BaseModel):
    ok: bool
    task_id: int


class TaskStatusResponse(BaseModel):
    task_id: int
    status: str
    mode: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pnl: float = 0.0
    trades_count: int = 0
    progress: Optional[dict] = None
    live_signals_count: int = 0


class ProgressRequest(BaseModel):
    task_id: int = Field(ge=1)
    progress: dict


class ProgressResponse(BaseModel):
    ok: bool
    task_id: int


# ──────────── 4 endpoints (Phase 1 mock) ────────────


@router.post(
    "/run-task",
    response_model=RunTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_token)],
)
async def run_task(req: RunTaskRequest) -> RunTaskResponse:
    """Phase 1 mock: 立即返 202, 不真正执行

    Phase 2: 异步启动 Backtrader 引擎 (后台 task)
    """
    return RunTaskResponse(
        task_id=req.task_id,
        status="accepted",
        msg=f"Phase 1 mock: task {req.task_id} (mode={req.mode}, stock={req.stock_code}) accepted. "
            f"Real execution wired up in Phase 2.",
    )


@router.post(
    "/stop-task",
    response_model=StopTaskResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def stop_task(req: StopTaskRequest) -> StopTaskResponse:
    """Phase 1 mock: 立即返 ok"""
    return StopTaskResponse(ok=True, task_id=req.task_id)


@router.get(
    "/tasks/{task_id}/status",
    response_model=TaskStatusResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def get_task_status(task_id: int) -> TaskStatusResponse:
    """Phase 1 mock: 返 'accepted' 状态"""
    return TaskStatusResponse(
        task_id=task_id,
        status="accepted",
        mode=None,
        started_at=None,
        finished_at=None,
        pnl=0.0,
        trades_count=0,
        progress=None,
        live_signals_count=0,
    )


@router.post(
    "/tasks/{task_id}/progress",
    response_model=ProgressResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def receive_progress(task_id: int, req: ProgressRequest) -> ProgressResponse:
    """Phase 1 mock: 立即返 ok

    Phase 2: 写 DB strategy_task.progress (用乐观锁 version)
    """
    return ProgressResponse(ok=True, task_id=task_id)