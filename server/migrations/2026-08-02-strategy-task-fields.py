"""
Migration: 2026-08-02-strategy-task-fields.py

为 strategy_task 加 fields 列 (历史行情字段白名单)
存格式: 逗号分隔字段名, 例 'open,close,high,low,volume'
默认 'open,close,high,low' (兼容历史 task)

📌 参考 iquant/quota_his.py 的 FIELDS 配置:
  - open,close,high,low (基础 OHLC)
  - volume,amount (成交统计)
  - openInt (持仓量, 期货才有)
  - settlePrice (结算价)
"""
from sqlalchemy import text, inspect


def migrate(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        cols = [c["name"] for c in inspector.get_columns("strategy_task")]
        if "fields" not in cols:
            conn.execute(text(
                "ALTER TABLE strategy_task ADD COLUMN fields VARCHAR(64) NULL "
                "COMMENT '历史行情字段白名单, 默认 open,close,high,low'"
            ))
            print("[migration] added strategy_task.fields")
        else:
            print("[migration] strategy_task.fields already exists, skipped")
        conn.commit()


def rollback(engine):
    with engine.connect() as conn:
        cols = [c["name"] for c in inspect(engine).get_columns("strategy_task")]
        if "fields" in cols:
            conn.execute(text("ALTER TABLE strategy_task DROP COLUMN fields"))
            print("[migration] dropped strategy_task.fields")
        conn.commit()


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)