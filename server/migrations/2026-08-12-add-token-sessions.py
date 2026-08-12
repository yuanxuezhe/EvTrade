"""
2026-08-12-add-token-sessions.py — DB 迁移: 建 token_sessions 表 (ENGINE=MEMORY)

REQ-AUTH-IDLE-001 跨 worker 修复 (2026-08-12):
- v127.2 加 --workers 4 → 4 个独立 Python 进程
- 原 session cache 是模块级 dict → 每个进程一份 → 登录写 worker A, 鉴权读 worker B → 401
- 解决: token cache 落 MySQL (所有 worker 共享同一份)
- ENGINE=MEMORY: server-wide, 重启即清空 (保留"重启=全部失效"语义)

被自动调用: server/lifecycle/seed.py::_run_pending_migrations()
"""

from sqlalchemy import text, inspect


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def migrate(engine):
    """建 token_sessions 表 (幂等, 已存在则跳过)."""
    inspector = inspect(engine)
    table = "token_sessions"

    with engine.begin() as conn:
        if not _has_table(inspector, table):
            # ENGINE=MEMORY: 所有 worker 进程共享同一份数据 (server-wide)
            # 重启即清空 (用户期望: 后端重启 = 所有 token 失效)
            # 列大小估算: token_hash 64 + user_id 4 + role 16 + 2×DATETIME 16 = ~100B/行
            # 默认 max_heap_table_size=16MB → 可容纳 ~16 万活跃 token (充裕)
            conn.execute(text("""
                CREATE TABLE token_sessions (
                    token_hash    CHAR(64) NOT NULL,
                    user_id       INT NOT NULL,
                    role          VARCHAR(16) NOT NULL,
                    created_at    DATETIME NOT NULL,
                    last_seen_at  DATETIME NOT NULL,
                    PRIMARY KEY (token_hash),
                    INDEX ix_token_sessions_user (user_id),
                    INDEX ix_token_sessions_last_seen (last_seen_at)
                ) ENGINE=MEMORY DEFAULT CHARSET=utf8mb4
                  COMMENT='REQ-AUTH-IDLE-001 token session cache (跨 worker 共享, 重启即清空)'
            """))
            print("[migration] created table token_sessions (ENGINE=MEMORY)")
        else:
            print("[migration] token_sessions already exists, skipped")