"""
server/api/script_strategy/strategies.py — 策略 CRUD + 回测批次 + 实盘门禁 端点 (v123)

REST 端点 (前缀 /api/script-strategy):
  GET    /strategies                         策略列表
  GET    /strategies/{strategy_id}           策略详情 (含脚本)
  POST   /strategies                         创建 {name, script_id}
  PUT    /strategies/{strategy_id}           更新 (仅 user_id=me)
  DELETE /strategies/{strategy_id}           删除

  POST   /strategies/{strategy_id}/backtest  单次回测 / 参数扫描 (生成批次, 转发 strategy_exec)
  GET    /strategies/{strategy_id}/batches   批次列表 (GROUP BY batch_no)
  GET    /strategies/{strategy_id}/batches/{batch_no}/tasks  批次内任务表格数据

  POST   /strategies/{strategy_id}/live      实盘启动 (best_params 门禁, 转发 strategy_exec)

批次创建不执行; 运行时转发到独立服务 strategy_exec (8001), 202 Accepted 立即返回。
"""
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from server.auth.deps import get_current_user
from server.models.user import User
from server.services import script_strategy as svc
from server.services.script_strategy.strategies import StrategyError

log = logging.getLogger(__name__)

router = APIRouter()


# ─────────────── Pydantic schemas ───────────────


class StrategyCreate(BaseModel):
    name: str
    script_id: str  # v90+ 脚本 id 是用户自命名 varchar


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|active|archived)$")


class StrategyOut(BaseModel):
    strategy_id: int
    user_id: int
    script_id: str
    name: str
    status: str
    best_params: Optional[Dict[str, Any]] = None
    script: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BacktestRequest(BaseModel):
    """回测请求: mode=single (params) 或 mode=sweep (param_ranges)"""
    mode: str = Field("single", pattern="^(single|sweep)$")
    stock_code: str
    backtest_start_date: str = Field(..., description="YYYYMMDD")
    backtest_end_date: str = Field(..., description="YYYYMMDD")
    # single
    params: Optional[Dict[str, Any]] = None
    # sweep (v123 D5 类型驱动: int/float start/end/step 含端点, choice values, string 固定)
    param_ranges: Optional[Dict[str, Dict[str, Any]]] = None
    period: Optional[str] = Field(None, pattern="^(1d|1m|5m|15m|30m|60m)$")
    fields: Optional[str] = None
    metric: str = Field("sharpe", pattern="^(sharpe|total_return|calmar)$")
    concurrency: int = Field(2, ge=1, le=16)


class BacktestResponse(BaseModel):
    batch_no: int
    total_runs: int
    mode: str
    metric: str
    over_soft_limit: bool = False
    msg: str = "backtest accepted, running in background"


class LiveRequest(BaseModel):
    stock_code: str
    fields: Optional[str] = None


class LiveResponse(BaseModel):
    batch_no: int
    task_id: int
    mode: str = "live"
    msg: str = "live accepted, running in background"


class BatchOut(BaseModel):
    batch_no: Optional[int]
    created_at: Optional[str] = None
    mode: Optional[str] = None
    task_count: int = 0
    finished_count: int = 0
    failed_count: int = 0
    best_params: Optional[Dict[str, Any]] = None
    best_metric_value: Optional[float] = None


# ─────────────── forward helpers (→ strategy_exec) ───────────────


async def _forward_run_task(task_id: int, payload: Dict[str, Any]):
    """转发单任务运行 (回测/实盘) 到 strategy_exec /internal/run-task"""
    from server.config import settings
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}/internal/run-task",
                headers={"X-Internal-Token": settings.STRATEGY_EXEC_API_TOKEN},
                json=payload,
            )
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=503, detail={"code": "STRATEGY_EXEC_TIMEOUT", "msg": f"strategy_exec 请求超时: {e}"})
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail={"code": "STRATEGY_EXEC_UNAVAILABLE", "msg": f"strategy_exec 连接失败: {type(e).__name__} {e}"})
    if resp.status_code >= 400:
        try:
            err = resp.json()
            code = err.get("detail", {}).get("code", "STRATEGY_EXEC_ERROR") if isinstance(err.get("detail"), dict) else "STRATEGY_EXEC_ERROR"
            msg = err.get("detail", {}).get("msg", resp.text) if isinstance(err.get("detail"), dict) else str(err.get("detail", resp.text))
        except Exception:
            code, msg = "STRATEGY_EXEC_ERROR", resp.text
        raise HTTPException(status_code=resp.status_code, detail={"code": code, "msg": msg})


async def _forward_run_sweep(payload: Dict[str, Any]):
    """转发扫描批次到 strategy_exec /internal/run-sweep-task"""
    from server.config import settings
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}/internal/run-sweep-task",
                headers={"X-Internal-Token": settings.STRATEGY_EXEC_API_TOKEN},
                json=payload,
            )
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=503, detail={"code": "STRATEGY_EXEC_TIMEOUT", "msg": f"strategy_exec sweep 请求超时: {e}"})
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail={"code": "STRATEGY_EXEC_UNAVAILABLE", "msg": f"strategy_exec sweep 连接失败: {type(e).__name__} {e}"})
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail={"code": "STRATEGY_EXEC_ERROR", "msg": resp.text})


# ─────────────── Strategy CRUD ───────────────


@router.get("/strategies", response_model=List[StrategyOut])
def list_strategies_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="draft/active/archived"),
    only_mine: bool = Query(False, description="仅列自己的 (默认含派生自公开脚本的策略)"),
    user: User = Depends(get_current_user),
):
    return svc.list_strategies(
        user.id, is_admin=(user.role == "admin"), status=status_filter, only_mine=only_mine,
    )


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
def get_strategy_endpoint(strategy_id: int, user: User = Depends(get_current_user)):
    out = svc.get_strategy(strategy_id, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return out


@router.post("/strategies", response_model=StrategyOut, status_code=201)
def create_strategy_endpoint(req: StrategyCreate, user: User = Depends(get_current_user)):
    try:
        return svc.create_strategy(user.id, name=req.name, script_id=req.script_id)
    except StrategyError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "msg": e.msg})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
def update_strategy_endpoint(
    strategy_id: int, req: StrategyUpdate, user: User = Depends(get_current_user),
):
    patch = req.dict(exclude_unset=True)
    out = svc.update_strategy(strategy_id, user.id, user.role == "admin", patch)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return out


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy_endpoint(strategy_id: int, user: User = Depends(get_current_user)):
    ok = svc.delete_strategy(strategy_id, user.id, user.role == "admin")
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return None


# ─────────────── 回测 / 批次 ───────────────


@router.post(
    "/strategies/{strategy_id}/backtest",
    response_model=BacktestResponse,
    status_code=202,
)
async def backtest_endpoint(
    strategy_id: int, req: BacktestRequest, user: User = Depends(get_current_user),
):
    """单次回测 / 参数扫描: 生成 1 个批次 + N 行 task, 转发 strategy_exec 异步执行。

    mode=single: req.params (1 组)
    mode=sweep:  req.param_ranges 类型驱动展开 (int/float 含端点, choice 值列表, string 固定)
    """
    log.info(
        "[backtest] user=%s strategy_id=%d mode=%s stock=%s metric=%s",
        user.username, strategy_id, req.mode, req.stock_code, req.metric,
    )
    try:
        batch = svc.create_backtest_batch(
            user.id, strategy_id,
            mode=req.mode,
            stock_code=req.stock_code,
            backtest_start_date=req.backtest_start_date,
            backtest_end_date=req.backtest_end_date,
            params=req.params,
            param_ranges=req.param_ranges,
            period=req.period,
            fields=req.fields,
            metric=req.metric,
            concurrency=req.concurrency,
        )
    except StrategyError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "msg": e.msg})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})

    # 转发 strategy_exec
    if req.mode == "sweep":
        await _forward_run_sweep({
            "user_id": user.id,
            "strategy_id": strategy_id,
            "script_id": batch["script_id"],
            "stock_code": batch["stock_code"],
            "backtest_start_date": batch["backtest_start_date"],
            "backtest_end_date": batch["backtest_end_date"],
            "batch_no": batch["batch_no"],
            "param_ranges": req.param_ranges,
            "metric": req.metric,
            "concurrency": req.concurrency,
            "period": req.period,
            "task_ids": batch["task_ids"],
        })
    else:
        await _forward_run_task(batch["task_ids"][0], {
            "task_id": batch["task_ids"][0],
            "user_id": user.id,
            "strategy_id": strategy_id,
            "script_id": batch["script_id"],
            "stock_code": batch["stock_code"],
            "mode": "backtest",
            "params": req.params or {},
            "backtest_start_date": batch["backtest_start_date"],
            "backtest_end_date": batch["backtest_end_date"],
            "period": req.period,
            "fields": req.fields,
        })

    log.info("[backtest] strategy_id=%d batch_no=%d total_runs=%d forwarded OK",
             strategy_id, batch["batch_no"], batch["total_runs"])
    return BacktestResponse(
        batch_no=batch["batch_no"],
        total_runs=batch["total_runs"],
        mode=batch["mode"],
        metric=batch["metric"],
        over_soft_limit=batch["over_soft_limit"],
    )


@router.get("/strategies/{strategy_id}/batches", response_model=List[BatchOut])
def batches_endpoint(strategy_id: int, user: User = Depends(get_current_user)):
    out = svc.list_batches(strategy_id, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return out


@router.get("/strategies/{strategy_id}/batches/{batch_no}/tasks")
def batch_tasks_endpoint(
    strategy_id: int, batch_no: int, user: User = Depends(get_current_user),
):
    out = svc.list_batch_tasks(strategy_id, batch_no, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return out


# ─────────────── 实盘门禁 ───────────────


@router.post("/strategies/{strategy_id}/live", response_model=LiveResponse, status_code=202)
async def live_endpoint(
    strategy_id: int, req: LiveRequest, user: User = Depends(get_current_user),
):
    """实盘启动: 校验 strategy.best_params 非空 (否则 400 NO_BEST_PARAMS),
    用 best_params 建 1 行 live task (新 batch_no), 转发 strategy_exec。
    """
    try:
        batch = svc.create_live_batch(
            user.id, strategy_id, stock_code=req.stock_code, fields=req.fields,
        )
    except StrategyError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "msg": e.msg})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})

    await _forward_run_task(batch["task_id"], {
        "task_id": batch["task_id"],
        "user_id": user.id,
        "strategy_id": strategy_id,
        "script_id": batch["script_id"],
        "stock_code": batch["stock_code"],
        "mode": "live",
        "params": batch["params"],
        "fields": req.fields,
    })

    log.info("[live] strategy_id=%d task_id=%d batch_no=%d forwarded OK",
             strategy_id, batch["task_id"], batch["batch_no"])
    return LiveResponse(batch_no=batch["batch_no"], task_id=batch["task_id"])


__all__ = ["router"]
