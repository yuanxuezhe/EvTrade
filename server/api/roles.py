"""
server/api/roles.py — 角色管理 + RBAC 角色/权限 CRUD (roles-module change 2026-09-21)

端点 (全部 require_admin):
  GET    /api/roles                 — 列出所有角色 + 各自的 page_keys
  POST   /api/roles                 — 新建角色
  PATCH  /api/roles/{id}            — 改 display_name / description (不能改 name / is_builtin)
  DELETE /api/roles/{id}            — 删角色 (is_builtin=1 不能删; CASCADE 自动清 user_roles + role_permissions)
  PUT    /api/roles/{id}/permissions — 整体覆盖 page_keys (传 list 替旧 set)
  GET    /api/roles/{id}/permissions — 列出该 role 的 page_keys

附加端点 (管理用户 ↔ 角色):
  GET    /api/users/{id}/roles      — 用户已绑定角色 + page_keys
  PUT    /api/users/{id}/roles      — 整体覆盖用户角色 (传 role_name 列表)

合规:
  - 内置 role (is_builtin=1) 不能删除 / 不能改名 / 内部页面权限不能去掉 '*' (super_admin)
  - 最后 1 个 super_admin 不能解绑 (防锁死)
  - users 表 is_active=0 不能授予 role (无意义)
"""
from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from server.infra.db import db_session
from server.auth.deps import require_admin, get_current_user
from server.services.rbac import (
    get_role_with_permissions,
    list_roles_with_permissions,
    get_user_full_roles,
)
from server.tables import Row

router = APIRouter()

ROLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class RoleCreateRequest(BaseModel):
    name: str = Field(..., description="英文唯一 key (a-z0-9_-), 2-63 字符")
    display_name: str = Field(..., description="显示名 (中文)")
    description: Optional[str] = None
    page_keys: List[str] = Field(default_factory=list, description="授予的 page_keys 列表")


class RoleUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None


class RolePermissionsUpdateRequest(BaseModel):
    page_keys: List[str] = Field(..., description="覆盖该角色的所有 page_keys")


class UserRolesUpdateRequest(BaseModel):
    role_names: List[str] = Field(..., description="覆盖绑定: 用户将拥有这些角色 (列表无环无重)")


# ── helpers ──────────────────────────────────────────────────────────────────

def _grant_role_permissions(db, role_id: int, page_keys: List[str]):
    """整体覆盖 (DELETE + INSERT). 留 granted_at = NOW()"""
    db.execute(text("DELETE FROM role_permissions WHERE role_id = :rid"), {"rid": role_id})
    if page_keys:
        # 去重
        seen = []
        for pk in page_keys:
            if pk and pk not in seen:
                seen.append(pk)
        for pk in seen:
            db.execute(text("""
                INSERT INTO role_permissions (role_id, page_key)
                VALUES (:rid, :pk)
            """), {"rid": role_id, "pk": pk})


def _validate_page_keys(page_keys: List[str]):
    """轻校验: 不能空字符串, 长度 ≤ 64"""
    for pk in page_keys:
        if not isinstance(pk, str) or not pk or len(pk) > 64:
            raise HTTPException(
                status_code=400,
                detail=f"page_key 非法: '{pk}' (必须非空, 长度 ≤64)",
            )


def _is_last_super_admin(db, user_id: int) -> bool:
    """用户当前是唯一的 super_admin? 用于 PUT /users/{id}/roles 防锁死"""
    r = db.execute(text("""
        SELECT 1 FROM user_roles ur
         WHERE ur.user_id = :uid
           AND ur.role_id = (SELECT id FROM roles WHERE name = 'super_admin')
         LIMIT 1
    """), {"uid": user_id}).first()
    if not r:
        return False  # 自身不是 super_admin, 解绑 OK
    cnt = db.execute(text("""
        SELECT COUNT(*) FROM user_roles
         WHERE role_id = (SELECT id FROM roles WHERE name = 'super_admin')
    """)).scalar()
    return cnt <= 1  # 包括自己就 1 个 → 解绑后没人超管


def _set_user_roles(db, user_id: int, role_names: List[str]):
    """整体覆盖. 防最后 super_admin 解绑."""
    # 1. 防锁死
    current_roles = get_user_full_roles(db, user_id)
    had_super = any(r["name"] == "super_admin" for r in current_roles)
    will_have_super = "super_admin" in role_names
    if had_super and not will_have_super and _is_last_super_admin(db, user_id):
        raise HTTPException(
            status_code=400,
            detail={"code": "LAST_SUPER_ADMIN", "msg": "不能解除最后一个 super_admin 的角色绑定 (会锁死系统)"},
        )

    # 2. 解析 role_name → role_id (含 404)
    if role_names:
        placeholders = ','.join(f':n{i}' for i in range(len(role_names)))
        ids = db.execute(text(f"""
            SELECT id, name FROM roles WHERE name IN ({placeholders})
        """), {f'n{i}': rn for i, rn in enumerate(role_names)}).fetchall()
        found = {r[1]: r[0] for r in ids}
        missing = [n for n in role_names if n not in found]
        if missing:
            raise HTTPException(
                status_code=404,
                detail={"code": "ROLE_NOT_FOUND", "msg": f"角色不存在: {missing}"},
            )
        # 去重保序
        seen = set()
        ordered = []
        for n in role_names:
            if n not in seen:
                seen.add(n)
                ordered.append(found[n])
    else:
        ordered = []

    # 3. 整体覆盖
    db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
    for rid in ordered:
        db.execute(text("""
            INSERT IGNORE INTO user_roles (user_id, role_id, granted_by)
            VALUES (:uid, :rid, :gby)
        """), {"uid": user_id, "rid": rid, "gby": None})


# ── 角色 CRUD ────────────────────────────────────────────────────────────────

@router.get("")
def api_list_roles(_: object = Depends(require_admin)):
    """列出所有角色 + 各自 page_keys"""
    with db_session() as db:
        return {"list": list_roles_with_permissions(db)}


@router.get("/{role_id}")
def api_get_role(role_id: int, _: object = Depends(require_admin)):
    """单个角色详情 + page_keys"""
    with db_session() as db:
        role = get_role_with_permissions(db, role_id)
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        return role


@router.post("", status_code=201)
def api_create_role(body: RoleCreateRequest, _admin: object = Depends(require_admin)):
    """新建角色 (含批量授 page_keys)"""
    name = body.name.strip().lower()
    if not ROLE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=f"角色 name 非法: '{name}' (a-z 开头, 小写字母数字_- 2-63 字符)",
        )
    _validate_page_keys(body.page_keys)
    with db_session() as db:
        # 重名探测
        existed = db.execute(text("SELECT id FROM roles WHERE name = :n LIMIT 1"), {"n": name}).first()
        if existed:
            raise HTTPException(status_code=409, detail=f"角色名已存在: {name}")
        try:
            db.execute(text("""
                INSERT INTO roles (name, display_name, description, is_builtin)
                VALUES (:n, :dn, :desc, 0)
            """), {"n": name, "dn": body.display_name, "desc": body.description})
            rid = db.execute(text("SELECT id FROM roles WHERE name = :n LIMIT 1"), {"n": name}).scalar()
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail=f"角色名冲突: {e.orig}")
        _grant_role_permissions(db, rid, body.page_keys)
        return get_role_with_permissions(db, rid)


@router.patch("/{role_id}")
def api_update_role(role_id: int, body: RoleUpdateRequest, _admin: object = Depends(require_admin)):
    """改 display_name / description (name + is_builtin 不可改, page_key 走专属端点)"""
    with db_session() as db:
        role = db.execute(text("""
            SELECT id, name, is_builtin FROM roles WHERE id = :rid
        """), {"rid": role_id}).first()
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        updates = {}
        if body.display_name is not None:
            updates["display_name"] = body.display_name
        if body.description is not None:
            updates["description"] = body.description
        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["rid"] = role_id
            db.execute(text(f"UPDATE roles SET {set_clause} WHERE id = :rid"), updates)
        return get_role_with_permissions(db, role_id)


@router.delete("/{role_id}")
def api_delete_role(role_id: int, _admin: object = Depends(require_admin)):
    """删角色 (FK CASCADE 自动清 user_roles + role_permissions). 内置不能删."""
    with db_session() as db:
        row = db.execute(text("SELECT name, is_builtin FROM roles WHERE id = :rid"), {"rid": role_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")
        if row[1]:
            raise HTTPException(
                status_code=400,
                detail={"code": "BUILTIN_ROLE", "msg": f"内置角色 {row[0]} 不可删除"},
            )
        db.execute(text("DELETE FROM roles WHERE id = :rid"), {"rid": role_id})
        return {"deleted": role_id, "name": row[0]}


# ── 角色 ↔ 页面权限 (CRUD 内细分) ───────────────────────────────────────────

@router.get("/{role_id}/permissions")
def api_get_role_permissions(role_id: int, _admin: object = Depends(require_admin)):
    with db_session() as db:
        role = db.execute(text("SELECT id, name FROM roles WHERE id = :rid"), {"rid": role_id}).first()
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        rows = db.execute(text("""
            SELECT page_key, granted_at FROM role_permissions
             WHERE role_id = :rid ORDER BY page_key
        """), {"rid": role_id}).fetchall()
        return {
            "role_id": role[0],
            "role_name": role[1],
            "permissions": [
                {"page_key": r[0], "granted_at": r[1].isoformat() if r[1] else None}
                for r in rows
            ],
        }


@router.put("/{role_id}/permissions")
def api_set_role_permissions(role_id: int, body: RolePermissionsUpdateRequest,
                             _admin: object = Depends(require_admin)):
    """整体覆盖 page_keys. super_admin 不能去掉 '*' (避免锁死)"""
    _validate_page_keys(body.page_keys)
    with db_session() as db:
        row = db.execute(text("SELECT name, is_builtin FROM roles WHERE id = :rid"), {"rid": role_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")
        if row[0] == "super_admin" and "*" not in body.page_keys:
            raise HTTPException(
                status_code=400,
                detail={"code": "SUPER_ADMIN_NEEDS_WILDCARD", "msg": "super_admin 必须保留 '*' 通配权限"},
            )
        _grant_role_permissions(db, role_id, body.page_keys)
        return api_get_role_permissions(role_id, _admin)


# ── 用户 ↔ 角色 ──────────────────────────────────────────────────────────────

@router.get("/users/{user_id}/roles")
def api_get_user_roles(user_id: int, _admin: object = Depends(require_admin)):
    with db_session() as db:
        if not db.execute(text("SELECT 1 FROM users WHERE id = :uid"), {"uid": user_id}).first():
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"user_id": user_id, "roles": get_user_full_roles(db, user_id)}


@router.put("/users/{user_id}/roles")
def api_set_user_roles(user_id: int, body: UserRolesUpdateRequest,
                       _admin: object = Depends(require_admin)):
    """整体覆盖用户角色"""
    with db_session() as db:
        if not db.execute(text("SELECT 1 FROM users WHERE id = :uid"), {"uid": user_id}).first():
            raise HTTPException(status_code=404, detail="用户不存在")
        _set_user_roles(db, user_id, body.role_names)
        return api_get_user_roles(user_id, _admin)