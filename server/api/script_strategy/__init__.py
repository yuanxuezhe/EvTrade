"""
server/api/script_strategy/__init__.py — 暴露 router 给 main.py include_router

v123: 合并三个子 router:
  - scripts.py    — 脚本库 (scripts CRUD / by-name / 模板)
  - tasks.py      — 任务 (list / detail / stop / delete / logs / signals / audit)
  - strategies.py — 策略 (CRUD / backtest 批次 / batches / live 门禁)
"""
from fastapi import APIRouter

from server.api.script_strategy.scripts import router as scripts_router
from server.api.script_strategy.strategies import router as strategies_router
from server.api.script_strategy.tasks import router as tasks_router

router = APIRouter()
router.include_router(scripts_router)
router.include_router(tasks_router)
router.include_router(strategies_router)

__all__ = ["router"]
