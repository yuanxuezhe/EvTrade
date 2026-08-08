"""
2026-08-09-cleanup-old-scripts-and-seed-demo.py — DB 迁移脚本 (Phase 5)

change `2026-08-09-strategy-exec-service`:
1. 删除 strategy_script 表全部 5 行旧用户脚本 (v90 自研引擎脚本, Backtrader 接口不兼容)
2. 插入 1 行新 demo 脚本 (mas_v1, Backtrader 双均线策略)

执行:
    python3 server/migrations/2026-08-09-cleanup-old-scripts-and-seed-demo.py

幂等:
- DELETE WHERE name IN (...): 重复跑无副作用
- INSERT: WHERE NOT EXISTS 子句, 已存在则跳过

⚠️ BACKUP 提醒: 跑之前先 dump
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade strategy_script > backup_strategy_script_20260809.sql

设计: 不依赖 strategy_exec 包 (避免 import backtrader),
       仅用 SQLAlchemy 1.4 (EvTrade 现有版本) 跑 SQL
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "server"))

try:
    from dotenv import load_dotenv
    # migration 在 server/migrations/ 下, .env 在 server/ 下
    _ENV_PATH = os.path.join(os.path.dirname(HERE), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (v20 MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported (v20 permanent standard). Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# 旧脚本 name 列表 (Phase 5 之前 DB 实际有的 5 个)
OLD_SCRIPT_NAMES = ["ma5_e2e", "test1", "ma5_test", "TEST", "v90test"]

# 新 demo 脚本 (mas_v1, Backtrader 双均线策略) — 内联代码避免依赖 strategy_exec
MAS_V1_CODE = '''import backtrader as bt

try:
    from strategy_exec.engines.backtrader.adapter import ProjectStrategy
except ImportError:
    ProjectStrategy = bt.Strategy


class MAStrategy(ProjectStrategy):
    """双均线交叉策略 (策略执行服务默认 demo)"""

    params = (
        ("fast", 5),
        ("slow", 20),
        ("qty", 100),
        ("rsi_period", 14),
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)
        self.rsi = bt.indicators.RSI(period=self.p.rsi_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

    def next(self):
        if len(self) < self.p.slow + 1:
            return
        price = self.data.close[0]
        ma5 = self.sma_fast[0]
        ma20 = self.sma_slow[0]
        rsi_v = self.rsi[0]

        if self.crossover[0] > 0 and not self.position:
            self.buy_signal(
                price=price,
                volume=self.p.qty,
                price_type="limit",
                indicators={"ma5": ma5, "ma20": ma20, "rsi": rsi_v},
                msg=f"金叉: ma5={ma5:.2f} 上穿 ma20={ma20:.2f}, RSI={rsi_v:.1f}",
            )
        elif self.crossover[0] < 0 and self.position:
            self.sell_signal(
                price=price,
                volume=self.position.size,
                price_type="limit",
                indicators={"ma5": ma5, "ma20": ma20, "rsi": rsi_v},
                msg=f"死叉: ma5={ma5:.2f} 下穿 ma20={ma20:.2f}, RSI={rsi_v:.1f}",
            )

    def notify_signal_published(self, signal_id: str, ok: bool) -> None:
        if not ok:
            self.log.warning(f"signal {signal_id} 推送失败, 请检查 RabbitMQ")
'''

MAS_V1_PARAMS_SCHEMA = [
    {"key": "fast", "type": "int", "min": 3, "max": 30, "step": 1, "default": 5, "desc": "快线周期"},
    {"key": "slow", "type": "int", "min": 10, "max": 120, "step": 1, "default": 20, "desc": "慢线周期"},
    {"key": "qty", "type": "int", "min": 100, "max": 10000, "step": 100, "default": 100, "desc": "下单数量 (整手)"},
    {"key": "rsi_period", "type": "int", "min": 6, "max": 30, "step": 1, "default": 14, "desc": "RSI 周期"},
]


def main() -> None:
    db_label = DATABASE_URL.split("@")[-1] if DATABASE_URL else "NONE"
    print(f"[start] cleanup + seed demo (db={db_label})")
    print(f"  old names to delete: {OLD_SCRIPT_NAMES}")
    print(f"  new demo to insert: mas_v1 (user_id=6, public=True)")

    with engine.begin() as conn:
        # ──── 步骤 0: 先清 FK 引用的 task + audit (旧脚本的运行记录)────
        print(f"\n[step 0] clean FK references: strategy_task + strategy_script_audit for old scripts...")
        # 先查要删的 script 的 (user_id, id) 集合
        placeholders = ", ".join(f":n{i}" for i in range(len(OLD_SCRIPT_NAMES)))
        params = {f"n{i}": name for i, name in enumerate(OLD_SCRIPT_NAMES)}
        script_keys = conn.execute(
            text(f"""
                SELECT user_id, id FROM strategy_script
                 WHERE name IN ({placeholders})
            """),
            params,
        ).all()
        if script_keys:
            print(f"  找到 {len(script_keys)} 个旧 script 的 PK, 删 task + audit...")
            for user_id, script_id in script_keys:
                # 删 task (FK -> strategy_script.user_id + .id)
                task_del = conn.execute(
                    text("DELETE FROM strategy_task WHERE user_id = :u AND script_id = :s"),
                    {"u": user_id, "s": script_id},
                )
                # 删 audit (FK -> strategy_task.id, 先 task 后 audit 不行 — FK 反过来)
                # strategy_script_audit.task_id 无 FK 到 strategy_script, 仅 FK 到 strategy_task.id
                # 但 task 已删, cascade 通常会带走 audit; 无 cascade 就单独删
                audit_del = conn.execute(
                    text("""
                        DELETE FROM strategy_script_audit
                         WHERE task_id IN (SELECT id FROM strategy_task WHERE user_id = :u AND script_id = :s)
                    """),
                    {"u": user_id, "s": script_id},
                )
                print(f"    [{user_id}] {script_id}: task 删 {task_del.rowcount} 行, audit 删 {audit_del.rowcount} 行")
        else:
            print(f"  无旧 script 匹配 (已清理过?), 跳过 FK 清理")

        # ──── 步骤 1: 删旧脚本 ────
        print(f"\n[step 1] delete old scripts by name...")
        placeholders = ", ".join(f":n{i}" for i in range(len(OLD_SCRIPT_NAMES)))
        params = {f"n{i}": name for i, name in enumerate(OLD_SCRIPT_NAMES)}
        result = conn.execute(
            text(f"DELETE FROM strategy_script WHERE name IN ({placeholders})"),
            params,
        )
        deleted_count = result.rowcount
        print(f"  ✓ deleted {deleted_count} rows")

        # ──── 步骤 2: 验证 demo 不存在再插 ────
        print(f"\n[step 2] seed new demo script (mas_v1, user_id=6)...")
        existing = conn.execute(
            text("SELECT id FROM strategy_script WHERE user_id = :u AND id = :i"),
            {"u": 6, "i": "mas_v1"},
        ).first()
        if existing is not None:
            print(f"  ⏭ demo 已存在 (id={existing[0]}), 跳过 INSERT")
        else:
            conn.execute(
                text("""
                    INSERT INTO strategy_script
                        (id, user_id, name, code, params_schema, description, status, is_public, created_at, updated_at)
                    VALUES
                        (:id, :user_id, :name, :code, :params_schema, :description, :status, :is_public, NOW(), NOW())
                """),
                {
                    "id": "mas_v1",
                    "user_id": 6,
                    "name": "mas_v1",
                    "code": MAS_V1_CODE,
                    "params_schema": json.dumps(MAS_V1_PARAMS_SCHEMA, ensure_ascii=False),
                    "description": "Backtrader 双均线策略 (策略执行服务默认 demo). "
                                   "5日上穿20日 → 金叉 → BUY signal; "
                                   "5日下穿20日 → 死叉 → SELL signal.",
                    "status": "active",
                    "is_public": 1,
                },
            )
            print(f"  ✓ inserted 1 row")

    # ──── 步骤 3: 验证 ────
    print(f"\n[verify] strategy_script 表当前内容:")
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, user_id, name, status, is_public, LENGTH(code) AS code_len "
                 "FROM strategy_script ORDER BY user_id, id")
        ).all()
        print(f"  total={len(rows)}")
        for r in rows:
            print(f"    [{r[1]}] {r[0]:12} {r[2]:12} status={r[3]:8} public={r[4]} code_len={r[5]}")

    engine.dispose()
    print("\n[OK] cleanup + seed 完成")


if __name__ == "__main__":
    main()