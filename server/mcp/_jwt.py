"""
server/mcp/_jwt.py — JWT 注入 helper (evtrade-mcp 内部)

所有 MCP tool 调用此 helper 解 JWT → 拿 user_id → 注入到下游 EvTrade REST 调用。
**禁止**让 LLM 通过 tool 参数指定 user_id；user_id **必须**从 JWT 来。

沙箱边界（REQ-ARCH-008）：
- LLM 不得指定 user_id
- tool 返回结果只含当前 user 的数据
"""
import os
import logging
from typing import Optional

import jwt  # python-jose (pyproject.toml 已锁 python-jose>=3.3.0,<4.0.0)
from jwt import PyJWTError  # type: ignore — python-jose 内部用 PyJWTError 兜底

log = logging.getLogger(__name__)

# 与 server/auth/* 一致 — 复用 JWT_SECRET (环境变量)
# 注意：不缓存到模块级 — 单测 monkeypatch os.environ 时能立即生效


def _jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "")


def _jwt_algorithm() -> str:
    return os.environ.get("JWT_ALGORITHM", "HS256")


class JWTError(Exception):
    """JWT 注入失败 — 上游 tool 应捕获并返 401 语义错误"""


def decode_user_id(jwt_token: str) -> int:
    """
    从 JWT 解出 user_id (int)。

    Raises:
        JWTError: token 缺失 / 无效 / 过期 / user_id 字段缺失
    """
    if not jwt_token:
        raise JWTError("jwt_token is empty")
    secret = _jwt_secret()
    if not secret:
        raise JWTError("JWT_SECRET not configured (server-side misconfig)")
    try:
        payload = jwt.decode(jwt_token, secret, algorithms=[_jwt_algorithm()])
    except PyJWTError as e:  # type: ignore
        raise JWTError(f"jwt decode failed: {e}") from e

    user_id = payload.get("user_id") or payload.get("sub")
    if user_id is None:
        raise JWTError("jwt payload missing user_id/sub")
    try:
        return int(user_id)
    except (TypeError, ValueError) as e:
        raise JWTError(f"user_id not int-castable: {user_id}") from e


def auth_headers(jwt_token: str) -> dict[str, str]:
    """构造 EvTrade REST API 用的 Authorization header"""
    return {"Authorization": f"Bearer {jwt_token}"}
