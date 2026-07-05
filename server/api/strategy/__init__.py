"""
api.strategy — facade（仿 api.orders 拆分模式）

实现已拆分到 2 个子模块：
- schemas.py    — 所有 Pydantic schemas
- endpoints.py  — 8 个 REST 端点（register_endpoints）

main.py 注册：from server.api.strategy import router; app.include_router(router)
"""
from fastapi import APIRouter

from server.api.strategy.endpoints import register_endpoints

router = APIRouter(prefix="/api/strategy", tags=["strategy"])
register_endpoints(router)

__all__ = ["router"]
