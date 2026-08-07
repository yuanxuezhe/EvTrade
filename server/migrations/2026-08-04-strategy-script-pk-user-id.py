"""
Migration: 2026-08-04-strategy-script-pk-user-id.py

策略脚本 PK 改 (user_id, id) 复合:
- id 列从 AUTO_INCREMENT INT 改成 varchar(64) (用户自命名, 通常是脚本文件名)
- 同用户的 id 不能重复 (PK 约束)
- 不同用户可以重名 (因为 user_id 不同)

新增 is_public 字段 (TINYINT 0/1, default 0):
- 用户可设置脚本公开 → 其他用户可看可复制
- 默认不公开

注意:
- strategy_task.script_id 外键会跟随改成 varchar(64)
- 复合 PK 自动覆盖原来的单列 PK id

清理要求: 已有 (id, user_id, name) 3 元组不允许 (user_id, id) 重名
"""
from sqlalchemy import text
from server.infra.db import engine


def _has_column(inspector, table_name, column_name):
    return any(c['name'] == column_name for c in inspector.get_columns(table_name))


def upgrade():
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(engine)
    with engine.begin() as conn:
        # 0. 先 drop strategy_task.script_id 上的 FK (不然改不动 strategy_script.id 类型)
        fk_rows = conn.execute(text("""
            SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_NAME='strategy_task' AND REFERENCED_TABLE_NAME='strategy_script'
        """)).fetchall()
        for (fk_name,) in fk_rows:
            try:
                conn.execute(text(f"ALTER TABLE strategy_task DROP FOREIGN KEY {fk_name}"))
            except Exception:
                pass

        # 1. 先去掉 id 的 AUTO_INCREMENT (如果还是 INT 类型)
        cols = insp.get_columns('strategy_script')
        id_col = next((c for c in cols if c['name'] == 'id'), None)
        if id_col and 'INT' in id_col['type'].__class__.__name__:
            conn.execute(text("ALTER TABLE strategy_script MODIFY COLUMN id INT NOT NULL"))
            conn.execute(text("ALTER TABLE strategy_script DROP PRIMARY KEY"))

        # 2. 改 id 列为 varchar(64)
        conn.execute(text("ALTER TABLE strategy_script MODIFY COLUMN id VARCHAR(64) NOT NULL"))

        # 3. 加 is_public 列 (默认 0 = 私有)，幂等
        if not _has_column(insp, 'strategy_script', 'is_public'):
            conn.execute(text("ALTER TABLE strategy_script ADD COLUMN is_public TINYINT NOT NULL DEFAULT 0"))

        # 4. 加复合 PK (如果主键还不是复合的)
        pk = insp.get_pk_constraint('strategy_script')
        pk_cols = sorted(pk.get('constrained_columns', []))
        if pk_cols != ['id', 'user_id']:
            # Drop existing PK first
            try:
                conn.execute(text("ALTER TABLE strategy_script DROP PRIMARY KEY"))
            except Exception:
                pass
            conn.execute(text("ALTER TABLE strategy_script ADD PRIMARY KEY (user_id, id)"))

        # 5. 删除 uk_strategy_script_user_name (如果存在)
        indexes = insp.get_indexes('strategy_script')
        if any(i['name'] == 'uk_strategy_script_user_name' for i in indexes):
            conn.execute(text("ALTER TABLE strategy_script DROP INDEX uk_strategy_script_user_name"))

        print("[migration] strategy_script PK → (user_id, id), id varchar(64), +is_public")

        # 6. strategy_task.script_id 改类型 + 加新 FK (复合)
        tcols = insp.get_columns('strategy_task')
        sid_col = next((c for c in tcols if c['name'] == 'script_id'), None)
        if sid_col and 'INT' in sid_col['type'].__class__.__name__:
            conn.execute(text("ALTER TABLE strategy_task MODIFY COLUMN script_id VARCHAR(64) NOT NULL"))

        # Add composite FK if not exists
        fk_check = conn.execute(text("""
            SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
            WHERE TABLE_NAME='strategy_task' AND CONSTRAINT_NAME='fk_task_script'
        """)).fetchone()
        if not fk_check:
            conn.execute(text("""
                ALTER TABLE strategy_task ADD CONSTRAINT fk_task_script
                FOREIGN KEY (user_id, script_id) REFERENCES strategy_script(user_id, id)
            """))

        print("[migration] strategy_task.script_id → varchar(64) + 复合 FK")


if __name__ == "__main__":
    upgrade()