"""
lifecycle/seed.py — 启动时建表 + 默认账号 seed

行为：
- 启动时调 validate_config() 验证配置
- init_db() 建表（SQLAlchemy create_all）
- 若 User 表为空，seed admin / trader 两个默认账号
- 已有用户则什么都不做（不覆盖、不重置）
"""
from server.db import init_db, SessionLocal
from server.models.user import User
from server.auth.security import hash_password
from server.config import validate_config


def init_and_seed():
    """Create tables and seed default accounts if no users exist.

    启动钩子函数。在 FastAPI on_event("startup") 中调用。
    """
    validate_config()
    init_db()
    db = SessionLocal()
    try:
        count = db.query(User).count()
        if count == 0:
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                role="admin",
                full_name="系统管理员",
                is_active=True,
                must_change_password=True,
            )
            trader = User(
                username="trader",
                password_hash=hash_password("trader123"),
                role="trader",
                full_name="默认交易员",
                is_active=True,
                must_change_password=True,
            )
            db.add(admin)
            db.add(trader)
            db.commit()
            print("[INIT] Created default accounts (users table was empty):")
            print("[INIT]   - admin / admin123 (role=admin)")
            print("[INIT]   - trader / trader123 (role=trader)")
            print("[INIT] Please change the password after first login.")
    finally:
        db.close()
