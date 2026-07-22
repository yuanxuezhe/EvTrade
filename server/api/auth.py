"""
Auth API: login, current user info, change password.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.models.user import User
from server.auth.security import (
    verify_password, hash_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
)
from server.auth.deps import get_current_user

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserInfoResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    must_change_password: bool = False
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    # v_next: 不限制旧密码 / 新密码长度 — 用户可自由修改
    new_password: str


class UpdateProfileRequest(BaseModel):
    email: str = None
    full_name: str = None


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Username + password → JWT token.

    async + run_in_threadpool: bcrypt.checkpw 是 CPU bound (rounds=12 ~250ms)，
    在 sync endpoint 会阻塞 Starlette threadpool（40 线程）→ 与 DB pool 形成
    复合死锁（threadpool 满 → DB session 不归还 → futex_wait_queue 僵死）。
    run_in_threadpool 把 bcrypt 扔到 anyio threadpool，不阻塞 event loop 与
    DB session 释放。
    """
    user = db.query(User).filter(User.username == form.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    # bcrypt in threadpool (CPU bound, blocking)
    ok = await run_in_threadpool(verify_password, form.password, user.password_hash)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已禁用")
    # Record last login
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    user_dict = user.to_dict()
    # v_next: 系统级开关 — 关掉后首次登录不再强制改密
    from server.services.sysconfig import get
    required = bool(get("must_change_password_required", 1))
    user_dict["must_change_password_required"] = required
    user_dict["must_change_password_effective"] = (
        bool(user_dict.get("must_change_password")) and required
    )
    return TokenResponse(
        access_token=token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_dict,
    )


@router.get("/me", response_model=UserInfoResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserInfoResponse(**current_user.to_dict())


@router.patch("/me", response_model=UserInfoResponse)
def update_profile(
    payload: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.email is not None:
        current_user.email = payload.email.strip() or None
    if payload.full_name is not None:
        current_user.full_name = payload.full_name.strip() or None
    db.commit()
    db.refresh(current_user)
    return UserInfoResponse(**current_user.to_dict())


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change password — 不校验旧密码 / 不限制新密码长度 / 不限制不能与旧密码相同。

    初始化时 admin 密码是 admin/admin123 (seed.py), 用户可自由修改, 不加任何限制。
    hash_password rounds=12 更慢 (~300ms)，必走 threadpool。
    """
    current_user.password_hash = await run_in_threadpool(hash_password, payload.new_password)
    current_user.must_change_password = False
    db.commit()
    return {"success": True, "message": "密码修改成功"}


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    """Stateless JWT — client just discards the token. Endpoint kept for audit."""
    return {"success": True}
