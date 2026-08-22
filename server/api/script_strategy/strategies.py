"""
server/api/script_strategy/strategies.py — 策略 CRUD + 回测批次 端点

REST 端点 (前缀 /api/script-strategy):
  GET    /strategies                         策略列表
  GET    /strategies/{strategy_id}           策略详情 (owner/admin 含脚本; 他人公开精简)
  POST   /strategies                         创建 {name, script_id, stock_code}
  PUT    /strategies/{strategy_id}           更新 name/status/is_public (仅 owner)
  DELETE /strategies/{strategy_id}           删除

  POST   /strategies/{strategy_id}/backtest  单次回测 / 参数扫描 (生成批次, 转发 strategy_exec)
  GET    /strategies/{strategy_id}/batches   批次列表 (GROUP BY batch_no)
  GET    /strategies/{strategy_id}/batches/{batch_no}/tasks  批次内任务表格数据
  POST   /strategies/{strategy_id}/batches/{batch_no}/retest  重测批次 (新 batch, 原批次废弃)

策略模块纯回测, 无实盘。策略绑定标的 (stock_code), 回测/批次/重测仅 owner 可访问
(他人公开 → 403 BACKTEST_FORBIDDEN, 他人私有/不存在 → 404 NO_STRATEGY)。

批次创建不执行; 运行时转发到独立服务 strategy_exec (8001), 202 Accepted 立即返回。
请求/响应 schema 在 schemas.py, 转发 helpers 在 forward.py (经本模块命名空间引入以兼容 monkeypatch)。
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from server.auth.deps import get_current_user
from server.services import script_strategy as svc
from server.services.script_strategy.strategies import StrategyError
from server.api.script_strategy.forward import _forward_run_task, _forward_run_sweep
from server.api.script_strategy.schemas import (
    BacktestRequest,
    BacktestResponse,
    BatchOut,
    StrategyCreate,
    StrategyOut,
    StrategyUpdate,
)
from server.tables import Row

log = logging.getLogger(__name__)

router = APIRouter()


# ─────────────── Strategy CRUD ───────────────


@router.get("/strategies", response_model=List[StrategyOut])
def list_strategies_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="draft/active/archived"),
    only_mine: bool = Query(False, description="仅列自己的 (默认含他人公开策略精简卡片)"),
    user: Row = Depends(get_current_user),
):
    return svc.list_strategies(
        user.id, is_admin=(user.role == "admin"), status=status_filter, only_mine=only_mine,
    )


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
def get_strategy_endpoint(strategy_id: int, user: Row = Depends(get_current_user)):
    out = svc.get_strategy(strategy_id, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return out


@router.post("/strategies", response_model=StrategyOut, status_code=201)
def create_strategy_endpoint(req: StrategyCreate, user: Row = Depends(get_current_user)):
    try:
        return svc.create_strategy(
            user.id, name=req.name, script_id=req.script_id, stock_code=req.stock_code,
        )
    except StrategyError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "msg": e.msg})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
def update_strategy_endpoint(
    strategy_id: int, req: StrategyUpdate, user: Row = Depends(get_current_user),
):
    patch = req.dict(exclude_unset=True)
    out = svc.update_strategy(strategy_id, user.id, user.role == "admin", patch)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    return out


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy_endpoint(strategy_id: int, user: Row = Depends(get_current_user)):
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
    strategy_id: int, req: BacktestRequest, user: Row = Depends(get_current_user),
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
        code_map = {
            "NO_STRATEGY": 404,
            "BACKTEST_FORBIDDEN": 403,
        }
        raise HTTPException(
            status_code=code_map.get(e.code, 400),
            detail={"code": e.code, "msg": e.msg},
        )
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
def batches_endpoint(strategy_id: int, user: Row = Depends(get_current_user)):
    try:
        out = svc.list_batches(strategy_id, user.id, is_admin=(user.role == "admin"))
    except StrategyError as e:
        code_map = {
            "NO_STRATEGY": 404,
            "BACKTEST_FORBIDDEN": 403,
        }
        raise HTTPException(
            status_code=code_map.get(e.code, 400),
            detail={"code": e.code, "msg": e.msg},
        )
    return out


@router.get("/strategies/{strategy_id}/batches/{batch_no}/tasks")
def batch_tasks_endpoint(
    strategy_id: int, batch_no: int, user: Row = Depends(get_current_user),
):
    try:
        out = svc.list_batch_tasks(
            strategy_id, batch_no, user.id, is_admin=(user.role == "admin"))
    except StrategyError as e:
        code_map = {
            "NO_STRATEGY": 404,
            "BACKTEST_FORBIDDEN": 403,
        }
        raise HTTPException(
            status_code=code_map.get(e.code, 400),
            detail={"code": e.code, "msg": e.msg},
        )
    return out


@router.post(
    "/strategies/{strategy_id}/batches/{batch_no}/retest",
    response_model=BacktestResponse,
    status_code=202,
)
async def retest_batch_endpoint(
    strategy_id: int, batch_no: int, user: Row = Depends(get_current_user),
):
    """重测批次: 按原批次配置重建新批次 (新 batch_no), 原批次 task 全部废弃,
    转发 strategy_exec 重新执行。运行中的批次返回 409 拒绝。
    """
    log.info("[retest] user=%s strategy_id=%d batch_no=%d", user.username, strategy_id, batch_no)
    try:
        batch = svc.retest_batch(strategy_id, batch_no, user.id, user.role == "admin")
    except StrategyError as e:
        code_map = {
            "NO_STRATEGY": 404,
            "BACKTEST_FORBIDDEN": 403,
            "BATCH_NOT_FOUND": 404,
            "BATCH_RUNNING": 409,
        }
        raise HTTPException(
            status_code=code_map.get(e.code, 400),
            detail={"code": e.code, "msg": e.msg},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})

    # 转发 strategy_exec (与原 backtest 提交一致)
    if batch["mode"] == "sweep":
        await _forward_run_sweep({
            "user_id": user.id,
            "strategy_id": strategy_id,
            "script_id": batch["script_id"],
            "stock_code": batch["stock_code"],
            "backtest_start_date": batch["backtest_start_date"],
            "backtest_end_date": batch["backtest_end_date"],
            "batch_no": batch["batch_no"],
            "param_ranges": batch["param_ranges"],
            "metric": batch["metric"],
            "concurrency": batch["concurrency"],
            "period": batch["period"],
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
            "params": batch["params"],
            "backtest_start_date": batch["backtest_start_date"],
            "backtest_end_date": batch["backtest_end_date"],
            "period": batch["period"],
            "fields": batch["fields"],
        })

    log.info("[retest] strategy_id=%d batch_no=%d→%d total_runs=%d forwarded OK",
             strategy_id, batch_no, batch["batch_no"], batch["total_runs"])
    return BacktestResponse(
        batch_no=batch["batch_no"],
        total_runs=batch["total_runs"],
        mode=batch["mode"],
        metric=batch["metric"],
        over_soft_limit=batch["over_soft_limit"],
    )


__all__ = ["router"]
