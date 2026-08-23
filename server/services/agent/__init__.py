"""
server/services/agent/__init__.py — EvTrade Agent 服务模块

包含：
- hermes_serve_client: Hermes serve daemon (JSON-RPC over WS) 客户端
- agent_confirm: pending_confirmations 状态机（二次确认协议）
"""
from .hermes_serve_client import HermesServeClient, HermesEvent, HermesUnreachableError, HermesError
from .agent_confirm import ConfirmRegistry, ConfirmTimeoutError, get_confirm_registry

__all__ = [
    "HermesServeClient",
    "HermesEvent",
    "HermesUnreachableError",
    "HermesError",
    "ConfirmRegistry",
    "ConfirmTimeoutError",
    "get_confirm_registry",
]
