"""
test_ws_hermes_token.py — REQ-AUTH-013 WS 直连 token=hermesagent 鉴权单元测试

覆盖 `server/ws/endpoint.py::_resolve_ws_user`:
- token=hermesagent → admin(id=6) 用户 dict (无条件, 用户决策)
- 合法 JWT → 返回 claims
- 垃圾/随机 token → None
- 空 token → None (由调用方在 query_params.get 之前兜底, 函数本身也应处理)
"""
import pytest

from server.auth.security import create_access_token, HERMES_AGENT_TOKEN
from server.ws.endpoint import _resolve_ws_user

ADMIN_IDENTITY = {"sub": "6", "id": 6, "role": "admin", "username": "admin"}


def test_hermesagent_maps_to_admin():
    """v129: token=hermesagent 直连 → admin(id=6) 身份."""
    user = _resolve_ws_user(HERMES_AGENT_TOKEN)
    assert user is not None
    assert user["id"] == 6
    assert user["role"] == "admin"
    assert user["sub"] == "6"


def test_hermesagent_constant_matches_grant_secret():
    """REQ-AUTH-011/013 单一事实源: grant 端点校验的也是这个字符串."""
    assert HERMES_AGENT_TOKEN == "hermesagent"


def test_valid_jwt_returns_claims():
    """合法 JWT → 原样返回 claims (不受 hermesagent 分支影响)."""
    claims = {"sub": "7", "id": 7, "role": "trader", "username": "trader"}
    token = create_access_token(dict(claims))
    user = _resolve_ws_user(token)
    assert user is not None
    assert user["id"] == 7
    assert user["role"] == "trader"


def test_garbage_token_returns_none():
    """随机/垃圾 token → None (close 4001)."""
    assert _resolve_ws_user("this-is-not-a-jwt") is None
    assert _resolve_ws_user("") is None
