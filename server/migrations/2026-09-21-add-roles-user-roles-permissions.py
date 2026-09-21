#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-21-add-roles-user-roles-permissions.py — DB 迁移 (roles-module change)

3 张表 CREATE TABLE IF NOT EXISTS (幂等):
  1. roles               — 角色定义, is_builtin 标记 4 个预置不可删
  2. user_roles          — 多对多: 一个用户多个角色
  3. role_permissions    — 角色 → 页面权限 (page_key 是前端路由 meta.page_key 字符串)

seed (幂等 INSERT IGNORE):
  - 4 个预置 role: super_admin / admin / trader / viewer
  - 预置 page_keys:
      super_admin: ['*']
      admin: dashboard / asset / cache-orders / cache-trades / cache-positions /
             cache-asset / admin-stock-config / data-completion-history-quote /
             users / roles / stkpool / system-config / system-init
      trader: dashboard / asset / trade / t0-trade / strategy-order / script-dev /
              script-task / stkpool / stkpool-view / cache-orders / cache-trades
      viewer: dashboard / asset / cache-orders / cache-trades / cache-positions
  - 把现有 users.role 字符串映射成 user_roles 行:
      admin → super_admin (兼容) + admin (业务)
      trader → trader
      viewer → viewer
    用 INSERT IGNORE, 重复运行不重复 (基于 PK 冲突跳过)

合规:
  - 仅 CREATE TABLE + INSERT IGNORE
  - 禁清表 (drop/truncate/delete) — EvTrade 硬规则
  - 禁改现有 data (users 表不被 ALTER)

用法:
    python3 server/migrations/2026-09-21-add-roles-user-roles-permissions.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
SERVER_DIR = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SERVER_DIR)

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(SERVER_DIR, ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine, inspect  # noqa: E402

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"Only MySQL is supported (permanent standard). Got URL: {DATABASE_URL[:80]!r}"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _table_exists(conn, table: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = :t
         LIMIT 1
    """), {"t": table}).first()
    return row is not None


def _index_exists(conn, table: str, index: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = :t
           AND INDEX_NAME = :i
         LIMIT 1
    """), {"t": table, "i": index}).first()
    return row is not None


# ── 1. CREATE TABLE roles ────────────────────────────────────────────────────

def create_roles_table(conn) -> None:
    if _table_exists(conn, "roles"):
        print("  [skip] table 'roles' already exists")
        return
    conn.execute(text("""
        CREATE TABLE roles (
            id INT NOT NULL AUTO_INCREMENT COMMENT '行主键',
            name VARCHAR(64) NOT NULL COMMENT '角色名 (英文唯一 key, 代码用)',
            display_name VARCHAR(128) NOT NULL DEFAULT '' COMMENT '显示名 (中文)',
            description VARCHAR(255) NULL COMMENT '描述',
            is_builtin TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=内置不可删 (super_admin/admin/trader/viewer)',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            PRIMARY KEY (id),
            UNIQUE KEY uk_roles_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        COMMENT='角色定义 (RBAC)'
    """))
    print("  [OK] created table 'roles'")


# ── 2. CREATE TABLE user_roles ───────────────────────────────────────────────

def create_user_roles_table(conn) -> None:
    if _table_exists(conn, "user_roles"):
        print("  [skip] table 'user_roles' already exists")
        return
    conn.execute(text("""
        CREATE TABLE user_roles (
            user_id INT NOT NULL COMMENT 'users.id',
            role_id INT NOT NULL COMMENT 'roles.id',
            granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '授权时间',
            granted_by INT NULL COMMENT '授权人 users.id (NULL=系统)',
            PRIMARY KEY (user_id, role_id),
            KEY ix_user_roles_user (user_id),
            KEY ix_user_roles_role (role_id),
            CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        COMMENT='用户 ↔ 角色 多对多'
    """))
    print("  [OK] created table 'user_roles'")


# ── 3. CREATE TABLE role_permissions ─────────────────────────────────────────

def create_role_permissions_table(conn) -> None:
    if _table_exists(conn, "role_permissions"):
        print("  [skip] table 'role_permissions' already exists")
        return
    conn.execute(text("""
        CREATE TABLE role_permissions (
            role_id INT NOT NULL COMMENT 'roles.id',
            page_key VARCHAR(64) NOT NULL COMMENT '前端路由 meta.page_key (e.g. trade.t0)',
            granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '授权时间',
            PRIMARY KEY (role_id, page_key),
            KEY ix_role_permissions_role (role_id),
            CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        COMMENT='角色 → 页面权限'
    """))
    print("  [OK] created table 'role_permissions'")


# ── 4. seed 4 built-in roles ─────────────────────────────────────────────────

BUILTIN_ROLES = [
    # (name, display_name, description, page_keys)
    ("super_admin", "超级管理员", "拥有所有页面权限 (page_key=* 通配)", ["*"]),
    ("admin",       "管理员",     "系统管理 + 业务查询 (后台运维)", [
        "dashboard", "asset", "cache-orders", "cache-trades", "cache-positions", "cache-asset",
        "admin-stock-config", "data-completion-history-quote",
        "users", "roles", "stkpool", "system-config", "system-init",
    ]),
    ("trader",      "交易员",     "下单 + 策略 + 查询", [
        "dashboard", "asset", "trade", "t0-trade", "strategy-order",
        "script-dev", "script-task", "stkpool", "stkpool-view",
        "cache-orders", "cache-trades",
    ]),
    ("viewer",      "观察者",     "只读：仪表盘 + 资金 + 委托/成交/持仓查询", [
        "dashboard", "asset", "cache-orders", "cache-trades", "cache-positions",
    ]),
]


def seed_builtin_roles(conn) -> None:
    """INSERT IGNORE 4 预置 role (重复跑不重复插)."""
    inserted = 0
    for name, display_name, description, _pks in BUILTIN_ROLES:
        result = conn.execute(text("""
            INSERT IGNORE INTO roles (name, display_name, description, is_builtin)
            VALUES (:n, :dn, :desc, 1)
        """), {"n": name, "dn": display_name, "desc": description})
        if result.rowcount:
            inserted += 1
    print(f"  [OK] seeded builtin roles (新插 {inserted} / 共 {len(BUILTIN_ROLES)})")


def seed_role_permissions(conn) -> None:
    """INSERT IGNORE 4 预置 role 的 page_keys (重复跑不重复插)."""
    inserted = 0
    for name, _dn, _desc, page_keys in BUILTIN_ROLES:
        role_id = conn.execute(text("""
            SELECT id FROM roles WHERE name = :n LIMIT 1
        """), {"n": name}).scalar()
        if role_id is None:
            continue
        for page_key in page_keys:
            r = conn.execute(text("""
                INSERT IGNORE INTO role_permissions (role_id, page_key)
                VALUES (:rid, :pk)
            """), {"rid": role_id, "pk": page_key})
            inserted += r.rowcount or 0
    print(f"  [OK] seeded role_permissions ({inserted} 新 grants)")


# ── 5. seed 把现有 users.role 字符串映射到 user_roles ────────────────────────

LEGACY_ROLE_MAP = {
    # users.role (旧) -> roles.name (新; 多值)
    "admin":  ["super_admin"],   # 演示账号都是 super_admin (admin 有 implies * 单)
    "trader": ["trader"],
    "viewer": ["viewer"],
    # 旧空 / 未知 role → 单值兜底 viewer (最严)
    "":       ["viewer"],
}


def seed_user_roles_from_legacy(conn) -> None:
    """读现有 users.role, INSERT IGNORE 一份 user_roles (admin 同时给 super_admin)."""
    if not _table_exists(conn, "user_roles"):
        print("  [skip] user_roles not yet created")
        return
    rows = conn.execute(text("""
        SELECT id, role FROM users
        WHERE id IS NOT NULL
    """)).fetchall()
    inserted = 0
    for user_id, legacy_role in rows:
        role_names = LEGACY_ROLE_MAP.get(legacy_role or "", ["viewer"])
        for rn in role_names:
            role_id = conn.execute(text("""
                SELECT id FROM roles WHERE name = :n LIMIT 1
            """), {"n": rn}).scalar()
            if role_id is None:
                continue
            r = conn.execute(text("""
                INSERT IGNORE INTO user_roles (user_id, role_id, granted_by)
                VALUES (:uid, :rid, NULL)
            """), {"uid": user_id, "rid": role_id})
            inserted += r.rowcount or 0
    print(f"  [OK] seeded user_roles from legacy (扫 {len(rows)} users, 新插 {inserted} grants)")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("[start] add rbac roles module (2026-09-21)")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        # 1. CREATE 3 表 (幂等)
        create_roles_table(conn)
        create_user_roles_table(conn)
        create_role_permissions_table(conn)

        # 2. seed 4 built-in roles (幂等)
        seed_builtin_roles(conn)
        seed_role_permissions(conn)

        # 3. seed user_roles from users.role 字符串 (幂等)
        seed_user_roles_from_legacy(conn)

    # ── verify ──
    print("\n[verify] 关键对象存在性:")
    insp = inspect(engine)
    tables = insp.get_table_names()
    for required in ("roles", "user_roles", "role_permissions"):
        marker = "[OK]" if required in tables else "[MISS]"
        col_count = len(insp.get_columns(required)) if required in tables else 0
        print(f"  {marker} table '{required}' ({col_count} 列)")

    if "roles" in tables:
        with engine.connect() as conn:
            cnt = conn.execute(text("SELECT COUNT(*) FROM roles")).scalar()
            builtin = conn.execute(text("SELECT COUNT(*) FROM roles WHERE is_builtin=1")).scalar()
            print(f"  [data] roles 总 {cnt}, 内置 {builtin} (期望 ≥4)")

    if "user_roles" in tables:
        with engine.connect() as conn:
            cnt = conn.execute(text("SELECT COUNT(*) FROM user_roles")).scalar()
            print(f"  [data] user_roles grant 总 {cnt}")

    if "role_permissions" in tables:
        with engine.connect() as conn:
            cnt = conn.execute(text("SELECT COUNT(*) FROM role_permissions")).scalar()
            print(f"  [data] role_permissions 总 {cnt}")

    print("\n[done] 角色管理 + RBAC 3 表就绪")


if __name__ == "__main__":
    main()
