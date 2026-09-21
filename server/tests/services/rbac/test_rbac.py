"""
test_rbac.py — server/services/rbac.py 单元测试 (roles-module change 2026-09-21)

覆盖:
  - get_user_role_names (空 / 单 / 多)
  - get_user_page_keys (无 role / 含 * 通配 / 多 role 并集)
  - user_has_page_key (* 优先级 / 不含 → False)
  - user_has_role
  - get_role_with_permissions (存在 / 不存在)
  - list_roles_with_permissions
  - get_user_full_roles

合规 (2026-08-27 硬规则 — 测试 fixture 禁清数据):
  - 严禁 DELETE FROM users WHERE username NOT LIKE 't_%'
  - 严禁 TRUNCATE / DROP / ALTER AUTO_INCREMENT
  - 测试用户 t_rbac_* 前缀 → 测试完毕用 fixture 删
  - 测试创建的角色 t_rbac_* 前缀 → 测试完毕删 (含 CASCADE 自动清 user_roles/role_permissions)

依赖: server/migrations/2026-09-21-add-roles-user-roles-permissions.py 已跑过
      (4 内置 role + 现有 users 已 grant)
"""
import pytest
from sqlalchemy import text

from server.infra.db import SessionLocal
from server.services.rbac import (
    get_user_role_names,
    get_user_page_keys,
    user_has_page_key,
    user_has_role,
    get_role_with_permissions,
    list_roles_with_permissions,
    get_user_full_roles,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _create_t_user(s, username: str) -> int:
    """创建 t_ 前缀测试用户 (硬规允许), 返回 user_id. created_at NOT NULL DEFAULT 0 占位"""
    s.execute(text("""
        INSERT INTO users (username, password_hash, role, is_active, must_change_password, created_at, updated_at)
        VALUES (:u, 'test_hash', 'viewer', 1, 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')
    """), {"u": username})
    uid = s.execute(text("SELECT id FROM users WHERE username = :u"), {"u": username}).scalar()
    s.commit()
    return uid


def _create_t_role(s, name: str, display: str, is_builtin: bool = False) -> int:
    """创建 t_ 前缀测试角色 (含 CASCADE FK 兼容)"""
    s.execute(text("""
        INSERT INTO roles (name, display_name, description, is_builtin)
        VALUES (:n, :dn, :desc, :b)
    """), {"n": name, "dn": display, "desc": "test fixture", "b": 1 if is_builtin else 0})
    rid = s.execute(text("SELECT id FROM roles WHERE name = :n"), {"n": name}).scalar()
    s.commit()
    return rid


def _grant(s, user_id: int, role_id: int):
    s.execute(text("""
        INSERT IGNORE INTO user_roles (user_id, role_id, granted_by)
        VALUES (:u, :r, NULL)
    """), {"u": user_id, "r": role_id})
    s.commit()


def _grant_perm(s, role_id: int, page_key: str):
    s.execute(text("""
        INSERT IGNORE INTO role_permissions (role_id, page_key)
        VALUES (:r, :pk)
    """), {"r": role_id, "pk": page_key})
    s.commit()


# ── fixture: 每个测试后清 t_* 测试数据 ─────────────────────────────────────

@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    # cleanup: 仅清 t_ 前缀的 (硬规允许)
    s.execute(text("""
        DELETE FROM user_roles
         WHERE user_id IN (SELECT id FROM users WHERE username LIKE 't_rbac_%')
    """))
    s.execute(text("""
        DELETE FROM role_permissions
         WHERE role_id IN (SELECT id FROM roles WHERE name LIKE 't_rbac_%')
    """))
    s.execute(text("DELETE FROM roles WHERE name LIKE 't_rbac_%'"))
    s.execute(text("DELETE FROM users WHERE username LIKE 't_rbac_%'"))
    s.commit()
    s.close()


# ── 测试 ────────────────────────────────────────────────────────────────────

def test_get_user_role_names_empty(db):
    """无 role 用户 → []"""
    uid = _create_t_user(db, "t_rbac_noroles")
    assert get_user_role_names(db, uid) == []


def test_get_user_role_names_single(db):
    """单 role → ['trader'] (内置)"""
    uid = _create_t_user(db, "t_rbac_trader")
    # 绑 trader (内置预置必有)
    trader_id = db.execute(text("SELECT id FROM roles WHERE name='trader'")).scalar()
    _grant(db, uid, trader_id)
    assert get_user_role_names(db, uid) == ["trader"]


def test_get_user_role_names_multiple(db):
    """多 role → 多个 (按 roles.id ASC)"""
    uid = _create_t_user(db, "t_rbac_multi")
    super_id = db.execute(text("SELECT id FROM roles WHERE name='super_admin'")).scalar()
    trader_id = db.execute(text("SELECT id FROM roles WHERE name='trader'")).scalar()
    # super_admin.id < trader.id (按 seed 顺序)
    _grant(db, uid, super_id)
    _grant(db, uid, trader_id)
    names = get_user_role_names(db, uid)
    assert names == ["super_admin", "trader"]


def test_get_user_page_keys_super_admin_wildcard(db):
    """super_admin 含 '*' → {'*'}"""
    uid = _create_t_user(db, "t_rbac_super")
    super_id = db.execute(text("SELECT id FROM roles WHERE name='super_admin'")).scalar()
    _grant(db, uid, super_id)
    keys = get_user_page_keys(db, uid)
    assert keys == {"*"}


def test_get_user_page_keys_intersect(db):
    """无通配 → 多个 role page_keys 取并集"""
    uid = _create_t_user(db, "t_rbac_intersect")
    rid1 = _create_t_role(db, "t_rbac_viewer_x", "1")
    rid2 = _create_t_role(db, "t_rbac_trader_x", "2")
    _grant_perm(db, rid1, "dashboard")
    _grant_perm(db, rid1, "asset")
    _grant_perm(db, rid2, "asset")
    _grant_perm(db, rid2, "trade")
    _grant(db, uid, rid1)
    _grant(db, uid, rid2)
    keys = get_user_page_keys(db, uid)
    assert keys == {"dashboard", "asset", "trade"}


def test_get_user_page_keys_no_role(db):
    """无 role → 空 set"""
    uid = _create_t_user(db, "t_rbac_empty")
    assert get_user_page_keys(db, uid) == set()


def test_user_has_page_key_wildcard(db):
    """* 通配 → 任意 page_key 都 True"""
    uid = _create_t_user(db, "t_rbac_wild")
    super_id = db.execute(text("SELECT id FROM roles WHERE name='super_admin'")).scalar()
    _grant(db, uid, super_id)
    assert user_has_page_key(db, uid, "anything.you.want") is True
    assert user_has_page_key(db, uid, "system-config") is True


def test_user_has_page_key_match(db):
    """page_key 在 set → True"""
    uid = _create_t_user(db, "t_rbac_match")
    trader_id = db.execute(text("SELECT id FROM roles WHERE name='trader'")).scalar()
    _grant(db, uid, trader_id)
    # trader 内置有 'trade'
    assert user_has_page_key(db, uid, "trade") is True
    # 没 'system-init'
    assert user_has_page_key(db, uid, "system-init") is False


def test_user_has_role_true(db):
    rid = db.execute(text("SELECT id FROM roles WHERE name='viewer'")).scalar()
    uid = _create_t_user(db, "t_rbac_has")
    _grant(db, uid, rid)
    assert user_has_role(db, uid, "viewer") is True


def test_user_has_role_false(db):
    rid = db.execute(text("SELECT id FROM roles WHERE name='viewer'")).scalar()
    uid = _create_t_user(db, "t_rbac_hasnot")
    _grant(db, uid, rid)
    assert user_has_role(db, uid, "super_admin") is False


def test_get_role_with_permissions_existing(db):
    """trader role 详情 + page_keys 列表"""
    rid = db.execute(text("SELECT id FROM roles WHERE name='trader'")).scalar()
    role = get_role_with_permissions(db, rid)
    assert role is not None
    assert role["name"] == "trader"
    assert role["is_builtin"] is True
    assert "trade" in role["page_keys"]
    assert "t0-trade" in role["page_keys"]


def test_get_role_with_permissions_missing(db):
    """不存在 → None"""
    assert get_role_with_permissions(db, 99999) is None


def test_list_roles_with_permissions(db):
    """所有角色 + page_keys"""
    roles = list_roles_with_permissions(db)
    names = [r["name"] for r in roles]
    # 4 内置必有
    for required in ("super_admin", "admin", "trader", "viewer"):
        assert required in names
    # super_admin 的 page_keys 含 *
    super_role = next(r for r in roles if r["name"] == "super_admin")
    assert "*" in super_role["page_keys"]


def test_get_user_full_roles(db):
    """用户全部角色 + 各自 page_keys"""
    uid = _create_t_user(db, "t_rbac_full")
    rid1 = _create_t_role(db, "t_rbac_a", "A")
    rid2 = _create_t_role(db, "t_rbac_b", "B")
    _grant_perm(db, rid1, "p1")
    _grant_perm(db, rid2, "p2")
    _grant(db, uid, rid1)
    _grant(db, uid, rid2)
    full = get_user_full_roles(db, uid)
    assert len(full) == 2
    by_id = {r["id"]: r for r in full}
    assert by_id[rid1]["page_keys"] == ["p1"]
    assert by_id[rid2]["page_keys"] == ["p2"]


def test_get_user_full_roles_empty(db):
    uid = _create_t_user(db, "t_rbac_full_empty")
    assert get_user_full_roles(db, uid) == []