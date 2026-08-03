"""
Migration: 2026-08-02-strategy-task-progress.py

为 strategy_task 加 progress JSON 列 (实时回测进度)
格式: {"phase": "fetch_his_bars|backtest|grid|done", "current": 1, "total": 320,
       "bar_idx": 123, "total_bars": 7680, "elapsed_ms": 3500, "updated_at": "..."}
"""
from sqlalchemy import text, inspect


def migrate(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        cols = [c["name"] for c in inspector.get_columns("strategy_task")]
        if "progress" not in cols:
            conn.execute(text(
                "ALTER TABLE strategy_task ADD COLUMN progress JSON NULL "
                "COMMENT '实时回测进度 (phase/current/total/bar_idx/total_bars/elapsed_ms)'"
            ))
            print("[migration] added strategy_task.progress")
        else:
            print("[migration] strategy_task.progress already exists, skipped")
        conn.commit()


def rollback(engine):
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE strategy_task DROP COLUMN progress"))
            print("[migration] dropped strategy_task.progress")
        except Exception as e:
            print(f"[migration] rollback err: {e}")
        conn.commit()


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)
