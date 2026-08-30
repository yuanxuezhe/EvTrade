"""
server/api/script_strategy/forward.py — 转发 strategy_exec 的 HTTP helpers

职责单一: 把已落库的 task / 批次 payload 转发到 strategy_exec (8001) 异步执行。
- _forward_run_batch: 回测批次 (single+sweep 统一) → /internal/run-batch (worker 池 FIFO 队列)
- _forward_run_task: 单任务运行 (仅实盘母单 strategy_orders 用) → /internal/run-task
被 strategies.py / strategy_orders.py 以 `from .forward import ...` 引入,
monkeypatch 目标保持在调用方模块命名空间。
"""
from typing import Any, Dict

import httpx
from fastapi import HTTPException


async def _forward_run_batch(payload: Dict[str, Any]):
    """转发回测批次到 strategy_exec /internal/run-batch (统一 worker 池队列).

    change 2026-08-30-sweep-worker-queue: single (1 行) + sweep (N 行) 都走此端点。
    payload: {user_id, strategy_id, script_id, stock_code, backtest_start_date,
              backtest_end_date, batch_no, metric, concurrency, period}
    """
    from server.config import settings
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}/internal/run-batch",
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


async def _forward_run_task(task_id: int, payload: Dict[str, Any]):
    """转发单任务运行 (实盘母单) 到 strategy_exec /internal/run-task

    change 2026-08-30-sweep-worker-queue: 回测已改走 _forward_run_batch (worker 池);
    本函数仅余 live 母单 (strategy_orders) 使用。
    """
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