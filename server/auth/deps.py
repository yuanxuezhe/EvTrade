"""
FastAPI dependencies: authentication & role-based authorization.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from server.models.user import User
from server.auth.security import decode_token
from server.auth import session  # REQ-AUTH-IDLE-001: token session cache (10min idle + restart invalidation)
from server.tables import Users  # v81.9: User ORM → tables.Users

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
) -> User:
    """Return the User identified by the JWT, or raise 401.

    v81.9: 改走 server.tables.Users (compat: 仍返 ORM User-like 对象)
    REQ-AUTH-IDLE-001 (2026-07-31):
      - decode_token 通过后, 必须 is_valid(token) 检查内存 session cache
      - 10 分钟无交互 / 后端重启 → cache 失效 → 401 (前端自动跳 /login)
      - is_valid 通过 → touch(token) 重置 idle 计时
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # REQ-AUTH-IDLE-001: session cache 检查 (10min idle + 后端重启自动失效)
    if not session.is_valid(token):
        # 顺手清理过期条目
        session.revoke(token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # 鉴权通过 → 重置 idle 计时
    session.touch(token)

    user_id = claims.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="令牌缺少用户标识")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="令牌用户标识无效")
    # v81.9: 走 tables 接口 (Row 支持 getattr: role/is_active/email/full_name 等)
    user = Users.query_one(id=user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not getattr(user, 'is_active', True):
        raise HTTPException(status_code=403, detail="账号已禁用，请联系管理员")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Allow only admin users."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def require_trader(current_user: User = Depends(get_current_user)) -> User:
    """Allow admin or trader (not viewer)."""
    if current_user.role not in ("admin", "trader"):
        raise HTTPException(status_code=403, detail="只读账号无法执行此操作")
    return current_user
