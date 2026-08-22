"""
server/api/script_strategy/forward.py — 转发 strategy_exec 的 HTTP helpers

职责单一: 把已落库的 task / 批次 payload 转发到 strategy_exec (8001) 异步执行。
- _forward_run_task: 单任务运行 (回测/实盘) → /internal/run-task
- _forward_run_sweep: 扫描批次 → /internal/run-sweep-task
被 strategies.py 以 `from .forward import ...` 引入, monkeypatch 目标保持在 strategies 模块命名空间。
"""
from typing import Any, Dict

import httpx
from fastapi import HTTPException


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
