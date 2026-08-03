"""
Migration: 2026-08-02-strategy-task-live-signals.py

为 strategy_task 增加 live_signals JSON 列 (实盘信号流, 用户脚本 signal() + doorder 自动记录)
"""
from sqlalchemy import text, inspect


def migrate(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        cols = [c["name"] for c in inspector.get_columns("strategy_task")]
        if "live_signals" not in cols:
            conn.execute(text(
                "ALTER TABLE strategy_task ADD COLUMN live_signals JSON NULL "
                "COMMENT '实盘信号流: 用户 script signal() + doorder 自动记录 (限 500 条, LiveRunner 每 5s flush)'"
            ))
            print("[migration] added strategy_task.live_signals")
        else:
            print("[migration] strategy_task.live_signals already exists, skipped")
        conn.commit()


def rollback(engine):
    with engine.connect() as conn:
        cols = [c["name"] for c in inspect(engine).get_columns("strategy_task")]
        if "live_signals" in cols:
            conn.execute(text("ALTER TABLE strategy_task DROP COLUMN live_signals"))
            print("[migration] dropped strategy_task.live_signals")
        conn.commit()


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)