"""
server/api/script_strategy/__init__.py — 暴露 router 给 main.py include_router

v123: 合并两个子 router:
  - endpoints.py   — scripts + tasks (脚本库 / 任务详情 / stop / delete / logs / signals / audit)
  - strategies.py  — strategies (策略 CRUD / backtest 批次 / batches / live 门禁)
"""
from fastapi import APIRouter

from server.api.script_strategy.endpoints import router as endpoints_router
from server.api.script_strategy.strategies import router as strategies_router

router = APIRouter()
router.include_router(endpoints_router)
router.include_router(strategies_router)

__all__ = ["router"]
