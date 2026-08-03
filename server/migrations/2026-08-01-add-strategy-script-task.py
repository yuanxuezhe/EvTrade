"""
Migration: 2026-08-01-add-strategy-script-task.py

新增 2 张独立表 (script-strategy change):
  - strategy_script  : 用户编写的 Python 脚本 + 参数 schema
  - strategy_task    : 任务运行态 + 回测结果 + best_params

幂等：表已存在则跳过。
"""
from sqlalchemy import text, inspect


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def migrate(engine):
    """正向迁移：建 strategy_script + strategy_task 表"""
    inspector = inspect(engine)
    with engine.connect() as conn:
        # ──────────────── strategy_script ────────────────
        if not _has_table(inspector, "strategy_script"):
            conn.execute(text("""
                CREATE TABLE strategy_script (
                    id          INT NOT NULL AUTO_INCREMENT,
                    user_id     INT NOT NULL,
                    name        VARCHAR(64) NOT NULL,
                    code        LONGTEXT NOT NULL,
                    params_schema JSON NULL,
                    description VARCHAR(255) NOT NULL DEFAULT '',
                    status      VARCHAR(16) NOT NULL DEFAULT 'active',
                    created_at  DATETIME NOT NULL,
                    updated_at  DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    INDEX ix_strategy_script_user (user_id, status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='脚本策略：用户编写的 Python 源码 + 参数 schema'
            """))
            print("[migration] created table strategy_script")
        else:
            print("[migration] strategy_script already exists, skipped")

        # ──────────────── strategy_task ────────────────
        if not _has_table(inspector, "strategy_task"):
            conn.execute(text("""
                CREATE TABLE strategy_task (
                    id              INT NOT NULL AUTO_INCREMENT,
                    user_id         INT NOT NULL,
                    script_id       INT NOT NULL,
                    stock_code      VARCHAR(16) NOT NULL,
                    mode            VARCHAR(8) NOT NULL,
                    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
                    params          JSON NULL,
                    backtest_result JSON NULL,
                    best_params     JSON NULL,
                    backtest_start_date VARCHAR(8) NULL,
                    backtest_end_date   VARCHAR(8) NULL,
                    period          VARCHAR(8) NULL,
                    pnl             FLOAT NOT NULL DEFAULT 0.0,
                    positions       JSON NULL,
                    trades_count    INT NOT NULL DEFAULT 0,
                    started_at      DATETIME NULL,
                    finished_at     DATETIME NULL,
                    error_msg       VARCHAR(500) NULL,
                    created_at      DATETIME NOT NULL,
                    updated_at      DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    INDEX ix_strategy_task_user_status (user_id, status),
                    INDEX ix_strategy_task_script_mode (script_id, mode),
                    CONSTRAINT fk_strategy_task_script
                        FOREIGN KEY (script_id) REFERENCES strategy_script(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='脚本策略任务：回测 / 实盘运行态 + 结果'
            """))
            print("[migration] created table strategy_task")
        else:
            print("[migration] strategy_task already exists, skipped")

        conn.commit()


def rollback(engine):
    """逆向迁移：删 2 张表"""
    inspector = inspect(engine)
    with engine.connect() as conn:
        if _has_table(inspector, "strategy_task"):
            conn.execute(text("DROP TABLE strategy_task"))
            print("[migration] dropped table strategy_task")
        else:
            print("[migration] strategy_task does not exist, skipped")
        if _has_table(inspector, "strategy_script"):
            conn.execute(text("DROP TABLE strategy_script"))
            print("[migration] dropped table strategy_script")
        else:
            print("[migration] strategy_script does not exist, skipped")
        conn.commit()


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)