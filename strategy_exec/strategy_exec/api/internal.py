"""
strategy_exec.api.internal — 4 internal endpoint (Phase 2: 接真引擎)

Phase 1: 仅返 mock JSON
Phase 2: run_task 调 Backtrader backtest/live 引擎, 异步执行

所有 endpoint 需校验 X-Internal-Token
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from strategy_exec.config import get_settings
from strategy_exec.engines.backtrader.backtest import run_backtest
from strategy_exec.engines.backtrader.live import (
    start_live_runner, stop_live_runner, is_running,
)
from strategy_exec.engines.backtrader.sweep import (
    count_param_ranges,
    SWEEP_HARD_LIMIT,
    ALLOWED_METRICS,
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
    strategy_id: int = Field(ge=1)  # 任务归属策略 (best_params 回写目标)
    script_id: str = Field(min_length=1, max_length=64)
    stock_code: str = Field(min_length=1, max_length=16)
    mode: str = Field(pattern="^(backtest|live)$")
    params: Any = Field(default_factory=dict)
    backtest_start_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    backtest_end_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    period: Optional[str] = Field(default=None, pattern=r"^(1d|1m|5m|15m|30m|60m)$")
    fields: Optional[str] = Field(default=None)
    # 策略下单母单归因 (signal_consumer 读 parent_task_id 写 orders.task_id)
    parent_task_id: Optional[int] = Field(default=None, ge=1)
    strategy_name: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="before")
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


# ──────────── sweep schemas (strategy-batch-task-model) ────────────


class RunSweepTaskRequest(BaseModel):
    """sweep 启动请求 — 批次已由 EvTrade 预建好 task 行, strategy_exec 只跑.

    body: {user_id, strategy_id, script_id, stock_code, backtest_start_date,
           backtest_end_date, batch_no, param_ranges, metric, concurrency, period}
    """
    user_id: int = Field(ge=0)
    strategy_id: int = Field(ge=1)   # best_params 回写目标
    script_id: str = Field(min_length=1, max_length=64)
    stock_code: str = Field(min_length=1, max_length=16)
    backtest_start_date: str = Field(pattern=r"^\d{8}$")
    backtest_end_date: str = Field(pattern=r"^\d{8}$")
    batch_no: int = Field(ge=1)       # 批次号 (序号表 task_batch)
    param_ranges: Dict[str, Dict[str, Any]] = Field(min_length=1)
    metric: str = Field(default="sharpe")
    concurrency: int = Field(default=2, ge=1, le=16)
    period: Optional[str] = Field(default=None, pattern=r"^(1d|1m|5m|15m|30m|60m)$")

    @model_validator(mode="after")
    def _validate_specific(self):
        # metric 必须在白名单内
        if self.metric not in ALLOWED_METRICS:
            raise ValueError(
                f"metric 必须是 {ALLOWED_METRICS} 之一, 收到: {self.metric!r}"
            )
        # grid 大小硬上限检查 (EvTrade 已校验, strategy_exec 兜底)
        size = count_param_ranges(self.param_ranges)
        if size > SWEEP_HARD_LIMIT:
            raise ValueError(
                f"param_ranges 展开总组合数 {size} 超过硬上限 {SWEEP_HARD_LIMIT}"
            )
        return self


class RunSweepTaskResponse(BaseModel):
    """202 Accepted — 返 batch_no + 总数, 实际跑在后台"""
    batch_no: int
    total_runs: int
    msg: str = "sweep accepted, running in background"


# ──────────── batch (统一回测任务队列, change 2026-08-30-sweep-worker-queue) ────────────


class RunBatchRequest(BaseModel):
    """批次执行请求 — 批次 task 行已由 EvTrade 预建 (status='queued'), strategy_exec 起 worker 池跑.

    single (1 行) + sweep (N 行) 统一走此端点. 不含 param_ranges (组合已展开落库).
    body: {user_id, strategy_id, script_id, stock_code, backtest_start_date,
           backtest_end_date, batch_no, metric, concurrency, period}
    """
    user_id: int = Field(ge=0)
    strategy_id: int = Field(ge=1)
    script_id: str = Field(min_length=1, max_length=64)
    stock_code: str = Field(min_length=1, max_length=16)
    backtest_start_date: str = Field(pattern=r"^\d{8}$")
    backtest_end_date: str = Field(pattern=r"^\d{8}$")
    batch_no: int = Field(ge=1)
    metric: str = Field(default="sharpe")
    concurrency: int = Field(default=2, ge=1, le=16)
    period: Optional[str] = Field(default=None, pattern=r"^(1d|1m|5m|15m|30m|60m)$")

    @model_validator(mode="after")
    def _validate_metric(self):
        if self.metric not in ALLOWED_METRICS:
            raise ValueError(f"metric 必须是 {ALLOWED_METRICS} 之一, 收到: {self.metric!r}")
        return self


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
        "[run_task] task_id=%d mode=%s stock=%s script=%s strategy_id=%d",
        req.task_id, req.mode, req.stock_code, req.script_id, req.strategy_id,
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
                strategy_id=req.strategy_id,
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
                parent_task_id=req.parent_task_id,    # 母单归因
                strategy_name=req.strategy_name or "",  # 子单 user_def
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
    task_id: int, user_id: int, strategy_id: int, script_id: str, stock_code: str,
    params: dict, bars: list,
    backtest_start_date: Optional[str], backtest_end_date: Optional[str], period: str,
) -> None:
    """后台跑回测 (异常时更新 task status='failed')

    单次回测成功 → 把 params 回写 strategy.best_params (update_strategy_best=True)
    """
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
            strategy_id=strategy_id,
            update_strategy_best=True,
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


# ──────────── batch (统一回测任务队列, change 2026-08-30-sweep-worker-queue) ────────────
# 旧 run_sweep_batch (asyncio.gather 一把梭) 已弃用 → 统一走 worker 池. 保留 run_sweep_batch
# 函数体 (测试/兼容) 但端点不再调它.


async def _connect_publisher() -> None:
    """预连接 signal publisher 并绑定主 loop.

    缺失时首次 publish 在回测线程 (asyncio.to_thread) 内走 asyncio.run → 临时 loop, 关闭后
    后续 publish 报 "Event loop is closed" → 整批任务 signal 失败. 每个批次触发前调一次.
    """
    from strategy_exec.signal.publisher import get_publisher
    try:
        await get_publisher().connect()
    except Exception as e:
        log.warning("[worker] publisher connect failed (will retry on publish): %s", e)


async def _dispatch_batch(
    *, strategy_id: int, batch_no: int, user_id: int, script_id: str, stock_code: str,
    backtest_start_date: str, backtest_end_date: str,
    metric: str, concurrency: int, period: str,
) -> int:
    """起 worker 池后台跑批次 (立即返, 不阻塞). 返批次 task 总数 (前端展示用).

    K 线拉取在 worker 池内部 (失败 → log + 批次 task 保持 queued, 不 502 — 提交已成功入库).
    实际执行 + best_params 回写全在后台.
    """
    from strategy_exec.data_access import get_batch_tasks
    from strategy_exec.engines.backtrader.worker import run_worker_pool

    tasks = get_batch_tasks(strategy_id, batch_no)
    total_runs = len(tasks)
    log.info(
        "[dispatch_batch] strategy_id=%d batch_no=%d user=%d script=%s stock=%s metric=%s runs=%d concurrency=%d",
        strategy_id, batch_no, user_id, script_id, stock_code, metric, total_runs, concurrency,
    )
    await _connect_publisher()
    asyncio.create_task(
        run_worker_pool(
            strategy_id=strategy_id, batch_no=batch_no,
            user_id=user_id, script_id=script_id, stock_code=stock_code,
            backtest_start_date=backtest_start_date, backtest_end_date=backtest_end_date,
            period=period, concurrency=concurrency, metric=metric,
        ),
        name=f"worker-pool-{strategy_id}-{batch_no}",
    )
    return total_runs


class RunBatchResponse(BaseModel):
    """202 Accepted — 批次已入队, worker 池后台执行"""
    batch_no: int
    total_runs: int
    msg: str = "batch accepted, running in background worker pool"


@router.post(
    "/run-batch",
    response_model=RunBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_token)],
)
async def run_batch(req: RunBatchRequest) -> RunBatchResponse:
    """统一回测批次执行入口 — 立即 202, 后台起 worker 池 FIFO 有界并发跑.

    change 2026-08-30-sweep-worker-queue: single (1 行) + sweep (N 行) 统一走此端点。
    EvTrade 已预建批次 task 行 (status='queued'), strategy_exec 只起 worker 池执行。
    """
    total_runs = await _dispatch_batch(
        strategy_id=req.strategy_id, batch_no=req.batch_no,
        user_id=req.user_id, script_id=req.script_id, stock_code=req.stock_code,
        backtest_start_date=req.backtest_start_date, backtest_end_date=req.backtest_end_date,
        metric=req.metric, concurrency=req.concurrency, period=req.period or "1d",
    )
    return RunBatchResponse(batch_no=req.batch_no, total_runs=total_runs)


@router.post(
    "/run-sweep-task",
    response_model=RunSweepTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_token)],
)
async def run_sweep_task(req: RunSweepTaskRequest) -> RunSweepTaskResponse:
    """sweep 启动端点 (兼容旧接口) — 立即返 202 + batch_no, 转调统一 worker 池.

    change 2026-08-30-sweep-worker-queue: 旧 asyncio.gather 一把梭已弃用, 改走 worker 队列。
    param_ranges 仅用于算 total_runs (展示); 实际 task 已按组合落库。
    """
    total_runs = await _dispatch_batch(
        strategy_id=req.strategy_id, batch_no=req.batch_no,
        user_id=req.user_id, script_id=req.script_id, stock_code=req.stock_code,
        backtest_start_date=req.backtest_start_date, backtest_end_date=req.backtest_end_date,
        metric=req.metric, concurrency=req.concurrency, period=req.period or "1d",
    )
    return RunSweepTaskResponse(batch_no=req.batch_no, total_runs=total_runs)