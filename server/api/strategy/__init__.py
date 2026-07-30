"""
api.strategy — facade（仿 api.orders 拆分模式）

实现已拆分到 3 个子模块：
- schemas.py    — 所有 Pydantic schemas
- endpoints.py  — 8 个 REST 端点（register_endpoints）
- t0_endpoints.py — T0 策略 CRUD + 信号历史

main.py 注册：from server.api.strategy import router; app.include_router(router)
"""
from fastapi import APIRouter

from server.api.strategy.endpoints import register_endpoints
from server.api.strategy.t0_endpoints import register_t0_endpoints

router = APIRouter(prefix="/api/strategy", tags=["strategy"])
register_endpoints(router)
register_t0_endpoints(router)

__all__ = ["router"]
