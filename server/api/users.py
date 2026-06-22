"""
User CRUD API — admin only.
"""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.models.user import User
from server.auth.security import hash_password
from server.auth.deps import require_admin, get_current_user

router = APIRouter()

VALID_ROLES = {"admin", "trader", "viewer"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]{3,32}$")


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "trader"
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    new_password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_login_at: Optional[str] = None


def _validate_username(name: str):
    if not USERNAME_RE.match(name or ""):
        raise HTTPException(status_code=400, detail="用户名需3-32位字母/数字/_/-/.")


def _validate_password(pw: str):
    if not pw or len(pw) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")


def _validate_role(role: str):
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"角色必须是 {'/'.join(sorted(VALID_ROLES))} 之一",
        )


@router.get("", response_model=List[UserResponse])
def list_users(
    keyword: Optional[str] = None,
    role: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(User)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(
            (User.username.ilike(kw))
            | (User.email.ilike(kw))
            | (User.full_name.ilike(kw))
        )
    if role:
        q = q.filter(User.role == role)
    users = q.order_by(User.id.asc()).all()
    return [UserResponse(**u.to_dict()) for u in users]


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    _validate_username(payload.username)
    _validate_password(payload.password)
    _validate_role(payload.role)
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        email=(payload.email or None),
        full_name=(payload.full_name or None),
        is_active=payload.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(**user.to_dict())


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if payload.role is not None:
        _validate_role(payload.role)
        # Prevent demoting the last admin
        if user.role == "admin" and payload.role != "admin":
            admin_count = db.query(User).filter(User.role == "admin", User.is_active == True).count()
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="必须至少保留一个管理员")
        user.role = payload.role

    if payload.email is not None:
        user.email = payload.email.strip() or None
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip() or None
    if payload.is_active is not None:
        # Prevent disabling the last admin / self
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        if user.role == "admin" and not payload.is_active:
            admin_count = db.query(User).filter(User.role == "admin", User.is_active == True).count()
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="必须至少保留一个启用的管理员")
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return UserResponse(**user.to_dict())


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    _validate_password(payload.new_password)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"success": True, "message": "密码已重置"}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        admin_count = db.query(User).filter(User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="必须至少保留一个管理员")
    db.delete(user)
    db.commit()
    return {"success": True}
