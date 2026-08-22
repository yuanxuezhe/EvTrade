"""
User CRUD API — admin only.

tables API 访问风格 (strict user-pseudocode):
  - 无 Depends(get_db), 无 sqlalchemy.orm.Session, 无 server.db.get_db.
  - 严格按 MIGRATION_GUIDE.md:
      查   → Users.query_one(id=...) / Users.query_by('field', value) /
             Users.query_by_fields({...}) / Users.query_all()
      写   → Users.add_one({...}) / Users.update_one({...}, id=...)
             / Users.delete_one(id=...)  / obj.update(Users, id=obj.id)
      聚合 → aggregate('users', 'COUNT', '*', where='role=%s AND is_active', params=('admin',))
"""
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.tables.users import Users
from server.tables import aggregate
from server.auth.security import hash_password
from server.auth.deps import require_admin

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
    _: object = Depends(require_admin),
):
    """List users (admin only).

    关键词 + role 过滤: 全表 + 内存过滤
       (用户偏好: 数据量小, 全表 + 前端/服务侧过滤即可);
       role 单一精确字段过滤 → Users.query_by('role', role)
    """
    # role 精确过滤走 query_by (单字段非主键)
    if role:
        users = Users.query_by("role", role)
    else:
        users = Users.query_all()

    if keyword:
        kw = keyword.lower()
        users = [
            u for u in users
            if (u.username and kw in u.username.lower())
            or (u.email and kw in u.email.lower())
            or (u.full_name and kw in u.full_name.lower())
        ]

    return [UserResponse(**_format_row_dict(u)) for u in users]


def _format_row_dict(row) -> dict:
    """Row.to_dict() 返回原始 datetime, UserResponse 期望 str — 复用 utils.time.format_db_dt."""
    from server.utils.time import format_db_dt
    d = row.to_dict()
    for f in ("created_at", "updated_at", "last_login_at"):
        if d.get(f) is not None:
            d[f] = format_db_dt(d[f])
    return d


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreateRequest,
    _: object = Depends(require_admin),
):
    """Create user (admin only).

    重名校验: Users.query_by('username', payload.username, limit=1) → 0/1 行;
    写入: Users.add_one({...})  (内部 SQLAlchemy INSERT, 自动回填自增 PK)
    """
    _validate_username(payload.username)
    _validate_password(payload.password)
    _validate_role(payload.role)
    if Users.query_by("username", payload.username, limit=1):
        raise HTTPException(status_code=409, detail="用户名已存在")

    # 表 users.created_at/updated_at 是 NOT NULL 且无 SQL 默认值, 显式填
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user_row = Users.add_one({
        "username": payload.username,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "email": (payload.email or None),
        "full_name": (payload.full_name or None),
        "is_active": payload.is_active,
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    })
    return UserResponse(**_format_row_dict(user_row))


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    admin: object = Depends(require_admin),
):
    """Update user (admin only).

    Users.query_one(id=user_id) → user (Row); 改字段 → Users.update_one({...}, id=user_id)
    """
    user = Users.query_one(id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    data: dict = {}

    if payload.role is not None:
        _validate_role(payload.role)
        # Prevent demoting the last admin
        if user.role == "admin" and payload.role != "admin":
            admin_count = aggregate(
                "users", "COUNT", "*",
                where="`role` = %s AND `is_active`",
                params=("admin",),
            )
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="必须至少保留一个管理员")
        data["role"] = payload.role

    if payload.email is not None:
        data["email"] = payload.email.strip() or None
    if payload.full_name is not None:
        data["full_name"] = payload.full_name.strip() or None
    if payload.is_active is not None:
        # Prevent disabling the last admin / self
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        if user.role == "admin" and not payload.is_active:
            admin_count = aggregate(
                "users", "COUNT", "*",
                where="`role` = %s AND `is_active`",
                params=("admin",),
            )
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="必须至少保留一个启用的管理员")
        data["is_active"] = payload.is_active

    if data:
        user = Users.update_one(data, id=user.id)
    return UserResponse(**_format_row_dict(user))


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    _: object = Depends(require_admin),
):
    """Reset password (admin only).

    Users.update_one({"password_hash": hash}, id=user_id)
    """
    _validate_password(payload.new_password)
    user = Users.query_one(id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    Users.update_one({"password_hash": hash_password(payload.new_password)}, id=user.id)
    return {"success": True, "message": "密码已重置"}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    admin: object = Depends(require_admin),
):
    """Delete user (admin only).

    Users.delete_one(id=user_id) → bool
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    user = Users.query_one(id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        admin_count = aggregate(
            "users", "COUNT", "*",
            where="`role` = %s",
            params=("admin",),
        )
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="必须至少保留一个管理员")
    Users.delete_one(id=user.id)
    return {"success": True}