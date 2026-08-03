"""
Migration: 2026-08-02-strategy-script-unique-name.py

为 strategy_script 加唯一索引 (user_id, name)
保证每个用户的脚本名唯一, 防止同名覆盖

📌 已有同名数据 → 提示但不删 (CRUD 时校验)
📌 索引名: uk_strategy_script_user_name
"""
from sqlalchemy import text, inspect


def migrate(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        # 1. 查已有同名脚本 (user_id, name 重复)
        dup_rows = conn.execute(text(
            "SELECT user_id, name, COUNT(*) AS cnt FROM strategy_script "
            "GROUP BY user_id, name HAVING cnt > 1"
        )).fetchall()
        if dup_rows:
            print(f"[migration] 警告: 已有 {len(dup_rows)} 个 (user_id, name) 重复:")
            for r in dup_rows:
                print(f"  user_id={r[0]} name={r[1]!r} count={r[2]}")
            print("[migration] 请先手动重命名后再加 UNIQUE 约束 (别名: 'xxx_1')")

        # 2. 加 UNIQUE 索引
        indexes = inspector.get_indexes("strategy_script")
        uniq_exists = any(
            idx.get("unique") and set(idx.get("column_names", [])) == {"user_id", "name"}
            for idx in indexes
        )
        if not uniq_exists:
            conn.execute(text(
                "ALTER TABLE strategy_script ADD CONSTRAINT uk_strategy_script_user_name "
                "UNIQUE (user_id, name)"
            ))
            print("[migration] added strategy_script unique (user_id, name)")
        else:
            print("[migration] unique (user_id, name) already exists, skipped")
        conn.commit()


def rollback(engine):
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE strategy_script DROP INDEX uk_strategy_script_user_name"
            ))
            print("[migration] dropped unique (user_id, name)")
        except Exception as e:
            print(f"[migration] rollback err: {e}")
        conn.commit()


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)