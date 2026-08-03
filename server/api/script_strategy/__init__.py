"""
server/api/script_strategy/__init__.py — 暴露 router 给 main.py include_router
"""
from server.api.script_strategy.endpoints import router

__all__ = ["router"]