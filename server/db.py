"""
server/db.py — 顶层 re-export 兼容垫片

实际实现已迁至 `server.infra.db`，本文件保留 facade 以兼容既有 import 路径。
MySQL-only（SQLite 已禁用）,无 DB_PATH。
"""
from server.infra.db import (  # noqa: F401
    BASE_DIR,
    DATABASE_URL,
    engine,
    SessionLocal,
    Base,
    get_db,
    db_session,
    init_db,
)
