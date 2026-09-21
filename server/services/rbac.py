"""
server/services/rbac.py — RBAC helper (roles-module change 2026-09-21)

提供 4 个纯函数 + 1 个类缓存:
  - get_user_role_names(user_id) -> list[str]
  - get_user_page_keys(user_id) -> set[str]   (含 * 通配 → 全匹配)
  - user_has_page_key(user_id, page_key) -> bool
  - user_has_role(user_id, role_name) -> bool

设计:
  - 纯函数, 不依赖 fastapi 上下文 (services 层)
  - 内部用 SQL 直接读 user_roles → roles → role_permissions (3 表 JOIN)
  - 性能: 短 N 秒内 (3 张小表, 单 user 有 1-N 个 role, role 10-30 permissions)
  - 缓存: 不加 (复用 RBAC 命中频次不高; 用户登录 1 次 → 加载一次; 前端 cache)

调用方:
  - server/services/guards.py: require_page_key() FastAPI dep
  - server/api/roles.py: 角色 / permissions CRUD (内部调 helper 做权限校验)
  - server/api/auth.py: me 端点可返回 user.roles + user.page_keys 给前端
"""
from __future__ import annotations

from typing import Iterable, List, Set

from sqlalchemy import text
from sqlalchemy.orm import Session


# ── 核心 helper ──────────────────────────────────────────────────────────────

def get_user_role_names(db: Session, user_id: int) -> List[str]:
    """返回用户的所有角色名 (按 roles.id ASC), 无角色返回 []"""
    rows = db.execute(text("""
        SELECT r.name
          FROM user_roles ur
          JOIN roles r ON r.id = ur.role_id
         WHERE ur.user_id = :uid
         ORDER BY r.id ASC
    """), {"uid": user_id}).fetchall()
    return [r[0] for r in rows]


def get_user_page_keys(db: Session, user_id: int, *, role_names: list | None = None) -> Set[str]:
    """返回用户的页面权限集合 (page_key)

    行为:
      - 任一 role 含 '*' → 返回 {'*'} (通配, 全匹配)
      - 否则合并所有 role 的 page_keys (去重)
      - 无 role → 返回空 set
    """
    # 角色名可由调用方传入 (避免重复查)
    if role_names is None:
        role_names = get_user_role_names(db, user_id)
    if not role_names:
        return set()

    # 1. 通配: super_admin 用 '*' 通配
    placeholders = ','.join(f':r{i}' for i in range(len(role_names)))
    rows = db.execute(text(f"""
        SELECT DISTINCT page_key
          FROM role_permissions
         WHERE role_id IN (SELECT id FROM roles WHERE name IN ({placeholders}))
    """), {f'r{i}': rn for i, rn in enumerate(role_names)}).fetchall()

    keys = {r[0] for r in rows}
    if '*' in keys:
        return {'*'}  # 通配: 所有 page_key 都通过
    return keys


def user_has_page_key(db: Session, user_id: int, page_key: str,
                      *, role_names: list | None = None,
                      cached_keys: set | None = None) -> bool:
    """单 page_key 判定, 兼容 super_admin '*' 通配"""
    if cached_keys is not None:
        keys = cached_keys
    else:
        keys = get_user_page_keys(db, user_id, role_names=role_names)
    if '*' in keys:
        return True
    return page_key in keys


def user_has_role(db: Session, user_id: int, role_name: str) -> bool:
    """用户是否拥有某 role"""
    row = db.execute(text("""
        SELECT 1
          FROM user_roles ur
          JOIN roles r ON r.id = ur.role_id
         WHERE ur.user_id = :uid AND r.name = :rn
         LIMIT 1
    """), {"uid": user_id, "rn": role_name}).first()
    return row is not None


# ── 批量工具 ────────────────────────────────────────────────────────────────

def get_role_with_permissions(db: Session, role_id: int) -> dict | None:
    """单个角色 + 其 page_keys 列表 → 用于角色管理页详情"""
    row = db.execute(text("""
        SELECT id, name, display_name, description, is_builtin, created_at, updated_at
          FROM roles WHERE id = :rid
    """), {"rid": role_id}).first()
    if not row:
        return None
    pages = db.execute(text("""
        SELECT page_key FROM role_permissions
         WHERE role_id = :rid
         ORDER BY page_key
    """), {"rid": role_id}).fetchall()
    return {
        "id": row[0],
        "name": row[1],
        "display_name": row[2],
        "description": row[3],
        "is_builtin": bool(row[4]),
        "created_at": row[5].isoformat() if row[5] else None,
        "updated_at": row[6].isoformat() if row[6] else None,
        "page_keys": [p[0] for p in pages],
    }


def list_roles_with_permissions(db: Session) -> List[dict]:
    """所有角色 + 其 page_keys → 角色管理主表列表"""
    rows = db.execute(text("""
        SELECT id, name, display_name, description, is_builtin, created_at, updated_at
          FROM roles ORDER BY id ASC
    """)).fetchall()
    if not rows:
        return []
    role_ids = [r[0] for r in rows]
    placeholders = ','.join(f':id{i}' for i in range(len(role_ids)))
    perm_rows = db.execute(text(f"""
        SELECT role_id, page_key
          FROM role_permissions
         WHERE role_id IN ({placeholders})
         ORDER BY role_id, page_key
    """), {f'id{i}': rid for i, rid in enumerate(role_ids)}).fetchall()
    perms_by_role: dict[int, list[str]] = {}
    for rid, pk in perm_rows:
        perms_by_role.setdefault(rid, []).append(pk)
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "name": r[1],
            "display_name": r[2],
            "description": r[3],
            "is_builtin": bool(r[4]),
            "created_at": r[5].isoformat() if r[5] else None,
            "updated_at": r[6].isoformat() if r[6] else None,
            "page_keys": perms_by_role.get(r[0], []),
        })
    return result


def get_user_full_roles(db: Session, user_id: int) -> List[dict]:
    """用户拥有的角色 (含 page_keys 详细) — 用于用户管理页编辑 / me 端点"""
    rows = db.execute(text("""
        SELECT r.id, r.name, r.display_name, r.description, r.is_builtin
          FROM user_roles ur
          JOIN roles r ON r.id = ur.role_id
         WHERE ur.user_id = :uid
         ORDER BY r.id ASC
    """), {"uid": user_id}).fetchall()
    if not rows:
        return []
    role_ids = [r[0] for r in rows]
    placeholders = ','.join(f':id{i}' for i in range(len(role_ids)))
    perm_rows = db.execute(text(f"""
        SELECT role_id, page_key
          FROM role_permissions
         WHERE role_id IN ({placeholders})
         ORDER BY role_id, page_key
    """), {f'id{i}': rid for i, rid in enumerate(role_ids)}).fetchall()
    perms_by_role: dict[int, list[str]] = {}
    for rid, pk in perm_rows:
        perms_by_role.setdefault(rid, []).append(pk)
    return [{
        "id": r[0],
        "name": r[1],
        "display_name": r[2],
        "description": r[3],
        "is_builtin": bool(r[4]),
        "page_keys": perms_by_role.get(r[0], []),
    } for r in rows]


def get_user_flat_page_keys(db: Session, user_id: int) -> Set[str]:
    """用户所有 page_keys 的并集 (考虑通配) — 用于 me 端点 / 前端 store"""
    return get_user_page_keys(db, user_id)