"""
strategy_exec.api.health — GET /health

无鉴权, 用于健康检查 / 负载均衡探活
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from strategy_exec import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    ts: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """健康检查 — 返服务状态 + 版本"""
    return HealthResponse(
        status="ok",
        version=__version__,
        ts=datetime.now(timezone.utc).isoformat(),
    )