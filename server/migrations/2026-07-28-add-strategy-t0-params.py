"""
Migration: 2026-07-28-add-strategy-t0-params.py

为 strategy 表新增 t0_params JSON 列，用于存储 T0 策略的完整参数配置。
幂等：列已存在则跳过。
"""
from sqlalchemy import text, inspect


def migrate(engine):
    """正向迁移：添加 t0_params 列"""
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns("strategy")]

    with engine.connect() as conn:
        if "t0_params" not in columns:
            # MySQL
            conn.execute(text(
                "ALTER TABLE strategy ADD COLUMN t0_params JSON NULL COMMENT 'T0策略参数JSON'"
            ))
            print("[migration] added strategy.t0_params")
        else:
            print("[migration] strategy.t0_params already exists, skipped")

        conn.commit()


def rollback(engine):
    """逆向迁移：删除 t0_params 列"""
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns("strategy")]

    with engine.connect() as conn:
        if "t0_params" in columns:
            conn.execute(text("ALTER TABLE strategy DROP COLUMN t0_params"))
            print("[migration] dropped strategy.t0_params")
        else:
            print("[migration] strategy.t0_params does not exist, skipped")

        conn.commit()


if __name__ == "__main__":
    from server.infra.db import get_engine
    migrate(get_engine())
