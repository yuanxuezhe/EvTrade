"""
server/api/script_strategy/strategy_orders.py — 策略下单母单 REST 端点

REST 端点 (前缀 /api/script-strategy, 由 __init__.py 挂载):
  POST  /strategy-orders                      建母单 {strategy_id} → 201
  GET   /strategy-orders                      列我的 (admin 全部)
  GET   /strategy-orders/{order_id}           母单详情
  GET   /strategy-orders/{order_id}/children  母单子单列表 (orders strategy_type=2)
  POST  /strategy-orders/{order_id}/start     启动实盘 (校验 + 转发 strategy_exec)
  POST  /strategy-orders/{order_id}/stop      停止实盘 (转发 /internal/stop-task)
  POST  /strategy-orders/{order_id}/close     关闭母单 (终态)

错误码映射 (StrategyError → HTTP):
  STRATEGY_ORDER_NOT_FOUND    404
  NO_STRATEGY                  404 (他人私有 / 不存在)
  FORBIDDEN                    403 (他人公开策略建母单)
  NO_BEST_PARAMS              400 (无 best_params 不可建/启动)
  STRATEGY_ORDER_INVALID_STATE 409 (running 再 start / 非 running stop/close)
"""
import logging
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException

from server.api.script_strategy.forward import _forward_run_task
from server.api.script_strategy.schemas import (
    StartStopResponse,
    StrategyOrderCreate,
    StrategyOrderOut,
)
from server.auth.deps import get_current_user
from server.services import script_strategy as svc
from server.services.script_strategy.strategy_order_lifecycle import (
    build_start_forward_payload,
)
from server.services.script_strategy.strategy_orders import (
    STATUS_RUNNING,
    get_strategy_order,
    list_strategy_order_children,
)
from server.services.script_strategy.strategies import StrategyError
from server.tables import Row

log = logging.getLogger(__name__)

router = APIRouter()


# ─────────────── 错误码 → HTTP 映射 ───────────────

_HTTP_BY_CODE = {
    "STRATEGY_ORDER_NOT_FOUND": 404,
    "NO_STRATEGY": 404,
    "FORBIDDEN": 403,
    "NO_BEST_PARAMS": 400,
    "STRATEGY_ORDER_INVALID_STATE": 409,
}


def _raise_strategy_error(e: StrategyError) -> None:
    """统一错误映射."""
    raise HTTPException(status_code=_HTTP_BY_CODE.get(e.code, 400), detail={"code": e.code, "msg": e.msg})


# ─────────────── CRUD 端点 ───────────────

@router.post("/strategy-orders", response_model=StrategyOrderOut, status_code=201)
def create_strategy_order_endpoint(
    req: StrategyOrderCreate, user: Row = Depends(get_current_user),
):
    try:
        return svc.create_strategy_order(
            req.strategy_id, user.id, is_admin=(user.role == "admin"),
        )
    except StrategyError as e:
        _raise_strategy_error(e)


@router.get("/strategy-orders", response_model=List[StrategyOrderOut])
def list_strategy_orders_endpoint(user: Row = Depends(get_current_user)):
    return svc.list_strategy_orders(user.id, is_admin=(user.role == "admin"))


@router.get("/strategy-orders/{order_id}", response_model=StrategyOrderOut)
def get_strategy_order_endpoint(order_id: int, user: Row = Depends(get_current_user)):
    out = get_strategy_order(order_id, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_ORDER_NOT_FOUND"})
    return out


@router.get(
    "/strategy-orders/{order_id}/children",
    response_model=List[dict],
)
def list_strategy_order_children_endpoint(order_id: int, user: Row = Depends(get_current_user)):
    out = list_strategy_order_children(order_id, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_ORDER_NOT_FOUND"})
    return out


# ─────────────── 启停 / 关闭 端点 ───────────────

@router.post(
    "/strategy-orders/{order_id}/start",
    response_model=StartStopResponse,
    status_code=202,
)
async def start_strategy_order_endpoint(order_id: int, user: Row = Depends(get_current_user)):
    """启动实盘: 校验 + 建 live task + 转发 strategy_exec.

    service 层返 forward_payload, api 层负责 await HTTP 转发。
    """
    try:
        r = svc.start_strategy_order(
            order_id, user.id, is_admin=(user.role == "admin"),
        )
    except StrategyError as e:
        _raise_strategy_error(e)

    # 转发到 strategy_exec (异步, 已建 task 行)
    payload = r["forward_payload"]
    await _forward_run_task(r["active_task_id"], payload)

    log.info(
        "[strategy_order start] user=%s order_id=%d active_task_id=%d parent_task_id=%s",
        user.username, order_id, r["active_task_id"], payload.get("parent_task_id"),
    )
    return StartStopResponse(
        task_id=r["task_id"],
        status=r["status"],
        active_task_id=r["active_task_id"],
        strategy_name=r["strategy_name"],
        forward_payload=payload,
    )


@router.post(
    "/strategy-orders/{order_id}/stop",
    response_model=StartStopResponse,
)
async def stop_strategy_order_endpoint(order_id: int, user: Row = Depends(get_current_user)):
    """停止实盘: 校验 running → 改母单 status → 转发 /internal/stop-task."""
    try:
        r = svc.stop_strategy_order(
            order_id, user.id, is_admin=(user.role == "admin"),
        )
    except StrategyError as e:
        _raise_strategy_error(e)

    # 转发 stop-task 到 strategy_exec
    from server.config import settings

    stop_payload = {"task_id": r["active_task_id"]}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}{r['stop_url']}",
                headers={"X-Internal-Token": settings.STRATEGY_EXEC_API_TOKEN},
                json=stop_payload,
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        # stop 转发失败不阻断 (母单已改 status, runner 由客户端重试机制兜底)
        log.warning(
            "[strategy_order stop] forward failed: %s (order_id=%d active_task_id=%d, 母单状态已更新)",
            type(e).__name__, order_id, r["active_task_id"],
        )

    return StartStopResponse(
        task_id=r["task_id"],
        status=r["status"],
        active_task_id=r["active_task_id"],
        stop_url=r["stop_url"],
    )


@router.post(
    "/strategy-orders/{order_id}/close",
    response_model=StrategyOrderOut,
)
def close_strategy_order_endpoint(order_id: int, user: Row = Depends(get_current_user)):
    try:
        return svc.close_strategy_order(
            order_id, user.id, is_admin=(user.role == "admin"),
        )
    except StrategyError as e:
        _raise_strategy_error(e)


__all__ = ["router", "build_start_forward_payload"]
