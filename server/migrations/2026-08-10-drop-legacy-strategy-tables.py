"""
2026-08-10-drop-legacy-strategy-tables.py — DB 迁移: 清理旧策略引擎死表

删除旧策略引擎(regime/grid 参数策略)的 4 张表 + 旧 stocks 备份表:
  - strategy          (旧引擎策略, 0 行)
  - strategy_regime   (旧引擎参数集, 0 行)
  - strategy_grid     (旧引擎网格, 0 行)
  - strategy_audit    (旧引擎审计, 0 行)
  - stocks_legacy     (旧 stocks 备份, 0 行)

新脚本策略系统 (strategy_script / strategy_task / strategy_script_audit) 不受影响。

⚠️ 安全校验: 仅当表存在且为空(0 行)时才 DROP; 非空 → 拒绝并提示先人工确认。

⚠️ BACKUP 提醒:
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade strategy strategy_regime strategy_grid strategy_audit stocks_legacy > backup_20260810_legacy.sql

执行:
    python3 server/migrations/2026-08-10-drop-legacy-strategy-tables.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(HERE), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine, inspect

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (MySQL-only).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported. Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# 要删除的表 (仅允许空表)
TABLES_TO_DROP = ["strategy", "strategy_regime", "strategy_grid", "strategy_audit", "stocks_legacy"]


def main() -> None:
    print("[start] drop legacy strategy tables")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    insp = inspect(engine)
    existing = set(insp.get_table_names())

    with engine.begin() as conn:
        # 旧引擎表间有外键 (strategy_regime.grid 引用 strategy 等) → 先关外键检查
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for t in TABLES_TO_DROP:
            if t not in existing:
                print(f"  [skip] table '{t}' not exists")
                continue
            n = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
            if n and n > 0:
                print(f"  [REFUSE] table '{t}' is NOT empty ({n} rows). 请先人工确认后再删!")
                continue
            conn.execute(text(f"DROP TABLE `{t}`"))
            print(f"  [DROPPED] table '{t}' (was empty)")
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    # ──── 验证 ────
    remaining = set(inspect(engine).get_table_names())
    print("\n[verify] 剩余策略相关表:")
    for t in sorted(remaining):
        if any(k in t for k in ("strategy", "script", "task", "t0", "audit")):
            print(f"  {t}")
    dropped = [t for t in TABLES_TO_DROP if t not in remaining]
    print(f"\n[dropped] {dropped if dropped else 'none'}")
    engine.dispose()
    print("[DONE] migration 完成")


if __name__ == "__main__":
    main()
