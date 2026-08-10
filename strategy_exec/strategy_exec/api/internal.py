"""
strategy_exec.api.internal — 4 internal endpoint (Phase 2: 接真引擎)

Phase 1: 仅返 mock JSON
Phase 2: run_task 调 Backtrader backtest/live 引擎, 异步执行

所有 endpoint 需校验 X-Internal-Token
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, root_validator

from strategy_exec.config import get_settings
from strategy_exec.engines.backtrader.backtest import run_backtest
from strategy_exec.engines.backtrader.live import (
    start_live_runner, stop_live_runner, is_running,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


# ──────────── 鉴权 ────────────


async def verify_internal_token(x_internal_token: Optional[str] = Header(None)) -> None:
    """空 token 时跳过验证（strategy_exec_api_token 未配置 = 局域网不鉴权）"""
    settings = get_settings()
    if not settings.strategy_exec_api_token:
        return  # 局域网部署，不鉴权
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
    params: Any = Field(default_factory=dict)
    backtest_start_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    backtest_end_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    period: Optional[str] = Field(default=None, pattern=r"^(1d|1m|5m|15m|30m|60m)$")
    fields: Optional[str] = Field(default=None)

    @root_validator(pre=True)
    @classmethod
    def _parse_params_before(cls, values):
        if isinstance(values, dict) and "params" in values:
            p = values["params"]
            if isinstance(p, str):
                try:
                    import json
                    values["params"] = json.loads(p)
                except json.JSONDecodeError:
                    raise ValueError(f"params 必须是 dict 或有效 JSON，收到: {p!r}")
        return values


class RunTaskResponse(BaseModel):
    task_id: int
    status: str
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


# ──────────── 4 endpoints ────────────


@router.post(
    "/run-task",
    response_model=RunTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_token)],
)
async def run_task(req: RunTaskRequest) -> RunTaskResponse:
    """启动任务 (回测 or 实盘), 后台异步执行"""
    log.info(
        "[run_task] task_id=%d mode=%s stock=%s script=%s",
        req.task_id, req.mode, req.stock_code, req.script_id,
    )

    if req.mode == "backtest":
        # 拉历史 K 线 → 异步执行回测
        from strategy_exec.market_data.hq_history import fetch_his_bars
        from strategy_exec.data_access import update_task_status
        from strategy_exec.signal.publisher import get_publisher

        missing = []
        if not req.backtest_start_date:
            missing.append("backtest_start_date")
        if not req.backtest_end_date:
            missing.append("backtest_end_date")
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MISSING_DATES",
                    "msg": f"回测模式缺少必填参数: {', '.join(missing)}（格式 YYYYMMDD，如 20260101）",
                },
            )

        # 步骤1: 拉历史 K 线
        log.info(
            "[run_task] backtest step 1/2 fetch_his_bars start: stock=%s %s~%s period=%s",
            req.stock_code, req.backtest_start_date, req.backtest_end_date,
            req.period or "1d",
        )
        try:
            bars = await fetch_his_bars(
                stock_code=req.stock_code,
                start_date=req.backtest_start_date,
                end_date=req.backtest_end_date,
                period=req.period or "1d",
            )
        except Exception as e:
            log.error("[run_task] fetch bars failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "BROKER_ERROR",
                    "msg": f"broker his_hq 行情服务未响应: {e} —— 请确认 QMT 端历史行情(his_hq)服务已启动并消费队列 EvTrade.ReqHisHq 后重试",
                },
            )

        if not bars:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_DATA", "msg": "broker 未返回数据"},
            )

        log.info(
            "[run_task] backtest step 1/2 fetch_his_bars done: %d bars",
            len(bars),
        )

        # 预连接 publisher (减少首次 publish 延迟)
        try:
            await get_publisher().connect()
        except Exception as e:
            log.warning("[run_task] publisher connect failed (will retry on publish): %s", e)

        # 步骤2: 后台异步执行回测
        log.info("[run_task] backtest step 2/2 dispatch background task=%d", req.task_id)
        asyncio.create_task(
            _run_backtest_background(
                task_id=req.task_id,
                user_id=req.user_id,
                script_id=req.script_id,
                stock_code=req.stock_code,
                params=req.params,
                bars=bars,
                backtest_start_date=req.backtest_start_date,
                backtest_end_date=req.backtest_end_date,
                period=req.period or "1d",
            ),
            name=f"backtest-{req.task_id}",
        )

    elif req.mode == "live":
        # 实盘: 启动 LiveRunner
        from strategy_exec.data_access import update_task_status

        update_task_status(req.task_id, "running")
        try:
            await start_live_runner(
                task_id=req.task_id,
                user_id=req.user_id,
                script_id=req.script_id,
                stock_code=req.stock_code,
                params=req.params,
            )
        except Exception as e:
            log.error("[run_task] start live failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "LIVE_START_FAILED", "msg": str(e)},
            )

    return RunTaskResponse(
        task_id=req.task_id,
        status="accepted",
        msg=f"task {req.task_id} ({req.mode}) started in background",
    )


async def _run_backtest_background(
    task_id: int, user_id: int, script_id: str, stock_code: str,
    params: dict, bars: list,
    backtest_start_date: Optional[str], backtest_end_date: Optional[str], period: str,
) -> None:
    """后台跑回测 (异常时更新 task status='failed')"""
    log.info(
        "[backtest task=%d] background start: stock=%s bars=%d %s~%s period=%s",
        task_id, stock_code, len(bars), backtest_start_date, backtest_end_date, period,
    )
    try:
        await asyncio.to_thread(
            run_backtest,
            task_id=task_id,
            user_id=user_id,
            script_id=script_id,
            stock_code=stock_code,
            params=params,
            bars=bars,
            backtest_start_date=backtest_start_date,
            backtest_end_date=backtest_end_date,
            period=period,
        )
        log.info("[backtest task=%d] background done", task_id)
    except Exception as e:
        log.error("[backtest task=%d] background failed: %s", task_id, e)
        from strategy_exec.data_access import update_task_status
        try:
            update_task_status(task_id, "failed", error_msg=f"backtest exception: {e}")
        except Exception:
            pass


@router.post(
    "/stop-task",
    response_model=StopTaskResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def stop_task(req: StopTaskRequest) -> StopTaskResponse:
    """停止任务 (live 立即停; backtest 仅标 stopped)"""
    log.info("[stop_task] task_id=%d", req.task_id)
    if is_running(req.task_id):
        ok = await stop_live_runner(req.task_id)
        return StopTaskResponse(ok=ok, task_id=req.task_id)

    # 回测模式: 仅标记
    from strategy_exec.data_access import update_task_status
    try:
        update_task_status(req.task_id, "stopped")
        return StopTaskResponse(ok=True, task_id=req.task_id)
    except Exception as e:
        log.error("[stop_task] update status failed: %s", e)
        return StopTaskResponse(ok=False, task_id=req.task_id)


@router.get(
    "/tasks/{task_id}/status",
    response_model=TaskStatusResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def get_task_status(task_id: int) -> TaskStatusResponse:
    """查 task 状态 (读 DB)"""
    from strategy_exec.data_access import get_task

    task = get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND"},
        )

    progress = task.get("progress")
    live_signals = task.get("live_signals") or []

    return TaskStatusResponse(
        task_id=task_id,
        status=task.get("status", "unknown"),
        mode=task.get("mode"),
        started_at=task["started_at"].isoformat() if task.get("started_at") else None,
        finished_at=task["finished_at"].isoformat() if task.get("finished_at") else None,
        pnl=float(task.get("pnl") or 0.0),
        trades_count=int(task.get("trades_count") or 0),
        progress=progress if isinstance(progress, dict) else None,
        live_signals_count=len(live_signals) if isinstance(live_signals, list) else 0,
    )


@router.post(
    "/tasks/{task_id}/progress",
    response_model=ProgressResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def receive_progress(task_id: int, req: ProgressRequest) -> ProgressResponse:
    """接收 progress 回调 (Phase 2 一般不用 — strategy_exec 直接写 DB)"""
    from strategy_exec.data_access import update_task_progress
    try:
        update_task_progress(task_id, req.progress)
        return ProgressResponse(ok=True, task_id=task_id)
    except Exception as e:
        log.error("[progress task=%d] failed: %s", task_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PROGRESS_WRITE_FAILED", "msg": str(e)},
        )