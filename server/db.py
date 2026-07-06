"""
server/db.py — 顶层 re-export 兼容垫片（v13 改造）

实际实现已迁至 `server.infra.db`，本文件保留 facade 以兼容既有 import 路径。
"""
from server.infra.db import (  # noqa: F401
    BASE_DIR,
    DB_PATH,
    DATABASE_URL,
    engine,
    SessionLocal,
    Base,
    get_db,
    db_session,
    init_db,
)
