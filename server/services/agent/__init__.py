"""
server/services/agent/__init__.py — EvTrade Agent 服务模块

包含：
- hermes_serve_client: Hermes API server (:8642) /v1/runs REST + SSE 客户端

2026-08-23 升级：移除 ConfirmRegistry（二次确认由 Hermes API server 自身处理）。
"""
from .hermes_serve_client import (
    HermesServeClient,
    HermesEvent,
    HermesUnreachableError,
    HermesError,
    get_default_client,
    reset_default_client,
)

__all__ = [
    "HermesServeClient",
    "HermesEvent",
    "HermesUnreachableError",
    "HermesError",
    "get_default_client",
    "reset_default_client",
]