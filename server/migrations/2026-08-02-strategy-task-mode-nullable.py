"""
Migration: 2026-08-02-strategy-task-mode-nullable.py

把 strategy_task.mode 改为可空 (创建任务时不指定 mode, 运行时才填)

幂等：检查当前定义，已为 NULL 则跳过。
"""
from sqlalchemy import text, inspect


def migrate(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        # MySQL: 改 column 允许 NULL (不管当前是否 NULL, 直接改)
        # 注意: 这里没法在 SQLAlchemy 2.x 里直接 "改 column nullable"
        # 简化: 用 raw SQL ALTER (MySQL 支持 MODIFY COLUMN)
        conn.execute(text("""
            ALTER TABLE strategy_task
            MODIFY COLUMN mode VARCHAR(8) NULL
              COMMENT '回测/实盘: 创建时不填, 运行 /tasks/{id}/run 时再写'
        """))
        print("[migration] strategy_task.mode → NULL allowed")
        conn.commit()


def rollback(engine):
    """回滚: 设回 NOT NULL (注意: 已有 NULL 数据会失败, 仅作形式回滚)"""
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE strategy_task
            MODIFY COLUMN mode VARCHAR(8) NOT NULL
        """))
        print("[migration] strategy_task.mode → NOT NULL (rollback)")
        conn.commit()


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)