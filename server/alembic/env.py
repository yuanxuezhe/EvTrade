"""Alembic env.py — EvTrade 表结构迁移入口

工作流程：
  1. 改 ORM model（server/models/orm.py）
  2. alembic revision --autogenerate -m "description"
  3. 审查生成的 migration（server/alembic/versions/）
  4. alembic upgrade head
  5. python scripts/gen_tables.py          ← 更新 server/tables/ 代码

数据库 URL 从 EVTRADE_DB_URL 环境变量读取（与业务代码一致）。
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

# 确保 server/ 在 sys.path 中（alembic 从项目根目录调用时 prepend_sys_path 会处理，
# 但此处加一层保险）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ─── Alembic 配置 ───────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ─── 从环境变量读取 DB URL（与 server/infra/db.py 一致） ─────────
try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

DATABASE_URL = os.environ.get("EVTRADE_DB_URL", "")
if not DATABASE_URL.startswith("mysql"):
    # 兼容：如果没有环境变量，降级为空（离线模式用不到 URL）
    DATABASE_URL = ""

# ─── 导入 ORM 模型注册 metadata ─────────────────────────────────
# 这些 import 不实例化对象，只是让 declarative_base() 注册表定义
from server.models import user, orm  # noqa: F401
from server.infra.db import Base  # declarative_base() 单例

target_metadata = Base.metadata

# 绕过 configparser 的 % 插值解析（DB URL 含 %40 会报错）
# 直接通过 env.py 的 run_migrations_*/engine_from_config 不需要 ini 中的 URL
# 这里把 url 设为空占位符，实际连接参数在 run_migrations_online 中从 DATABASE_URL 读取
if not DATABASE_URL:
    DATABASE_URL = config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """离线模式（不连数据库，生成 SQL 脚本）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,       # 检测列类型变更
        compare_server_default=True,  # 检测默认值变更
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式（直连数据库执行迁移）"""
    connectable = create_engine(DATABASE_URL if DATABASE_URL else "mysql+pymysql://", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
