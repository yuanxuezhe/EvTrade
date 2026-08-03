"""
Migration: 2026-08-02-strategy-script-audit.py

为脚本策略增加 strategy_script_audit 表 (独立于已有规则引擎的 strategy_audit)

📌 区别:
- strategy_audit: 规则引擎 (grid/regime) 触发审计, strategy_id FK 到 strategy.id
- strategy_script_audit: 脚本策略 (用户 Python) 触发审计, task_id 指向 strategy_task.id

字段:
- task_id (FK strategy_task.id)
- stime / trd_date
- phase: bar / tick / on_init / on_finish
- trigger_type: BUY / SELL / SIGNAL (用户 signal() 信息类) / STOP / TP
- stock_code / price / volume
- indicators JSON (触发时指标快照)
- state JSON (触发时持仓+现金)
- msg TEXT (触发原因)
- order_no (实盘模式)
- payload JSON (其他)
- created_at
"""
from sqlalchemy import text, inspect


def migrate(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        if "strategy_script_audit" in inspector.get_table_names():
            print("[migration] strategy_script_audit already exists, skipped")
            conn.commit()
            return
        conn.execute(text("""
            CREATE TABLE strategy_script_audit (
                id           BIGINT NOT NULL AUTO_INCREMENT,
                task_id      INT NOT NULL,
                stime        VARCHAR(20) NOT NULL COMMENT 'bar/tick 时间 YYYYMMDDHHMMSS',
                trd_date     VARCHAR(8) NOT NULL COMMENT '交易日 YYYYMMDD',
                phase        VARCHAR(16) NOT NULL COMMENT 'bar / tick / on_init / on_finish',
                trigger_type VARCHAR(16) NOT NULL COMMENT 'BUY / SELL / SIGNAL / STOP / TP / INFO',
                stock_code   VARCHAR(16) NOT NULL,
                price        FLOAT NULL,
                volume       INT NULL,
                indicators   JSON NULL COMMENT '触发时指标快照 {MA5:..., RSI:...}',
                state        JSON NULL COMMENT '触发时状态 {position:N, cash:M}',
                msg          TEXT NULL COMMENT '触发原因 / 用户描述',
                order_no     VARCHAR(32) NULL COMMENT '实盘 broker 订单号',
                payload      JSON NULL COMMENT '其他信息',
                created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                KEY ix_audit_task_time (task_id, created_at),
                KEY ix_audit_task_date (task_id, trd_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        conn.commit()
        print("[migration] created table strategy_script_audit")


def rollback(engine):
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS strategy_script_audit"))
        conn.commit()
        print("[migration] dropped strategy_script_audit")


if __name__ == "__main__":
    from server.infra.db import engine
    migrate(engine)