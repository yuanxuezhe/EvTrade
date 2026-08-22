"""
lifecycle/seed.py — 启动时建表 + 默认账号 seed

行为：
- 启动时调 validate_config() 验证配置
- init_db() 建表（SQLAlchemy create_all）
- 若 User 表为空，seed admin / trader 两个默认账号
- 已有用户则什么都不做（不覆盖、不重置）
"""
from server.infra.db import init_db, SessionLocal
from server.models.user import User
from server.auth.security import hash_password
from server.config import validate_config
import importlib
import os
import time


def _run_pending_migrations():
    """Auto-run pending standalone migrations from server/migrations/ (idempotent).

    Tracks applied migrations in `_applied_migrations` table (created if missing).
    """
    from sqlalchemy import text
    from server.infra.db import engine

    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations')
    if not os.path.isdir(migrations_dir):
        return

    # Create tracking table
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _applied_migrations (
                name VARCHAR(255) PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # Load and run pending migrations
    migration_files = sorted(f for f in os.listdir(migrations_dir)
                             if f.endswith('.py') and not f.startswith('__')
                             and f != 'legacy-data-bootstrap.py')

    with engine.begin() as conn:
        applied = {row[0] for row in conn.execute(
            text("SELECT name FROM _applied_migrations")
        ).fetchall()}

    for fname in migration_files:
        if fname in applied:
            continue
        name = fname[:-3]  # strip .py
        try:
            mod = importlib.import_module(f"server.migrations.{name}")
            fn = getattr(mod, 'migrate', None) or getattr(mod, 'upgrade', None)
            if fn:
                print(f"[migrate] applying {name}...")
                t0 = time.monotonic()
                # Support both migrate(engine) and upgrade() signatures
                import inspect
                sig = inspect.signature(fn)
                if len(sig.parameters) >= 1:
                    fn(engine)
                else:
                    fn()
                print(f"[migrate] {name} done ({(time.monotonic()-t0)*1000:.0f}ms)")
            else:
                print(f"[migrate] skip {name} (no migrate/upgrade function)")
        except Exception as e:
            print(f"[migrate] {name} FAILED: {e}")
            # Don't record as applied on failure
            continue

        # Record as applied
        with engine.begin() as conn:
            conn.execute(text("INSERT IGNORE INTO _applied_migrations (name) VALUES (:name)"),
                         {"name": name})


def init_and_seed():
    """Create tables and seed default accounts if no users exist.

    启动钩子函数。在 FastAPI on_event("startup") 中调用。
    """
    validate_config()
    init_db()
    # Run pending standalone migrations
    try:
        _run_pending_migrations()
    except Exception:
        import traceback; traceback.print_exc()
        print("[INIT] migration error (continuing anyway)")
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
