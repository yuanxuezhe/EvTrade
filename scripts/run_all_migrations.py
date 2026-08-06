#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all_migrations.py — 统一运行所有迁移 + 查表数据状态

用法: 在项目根目录执行
    python scripts/run_all_migrations.py

依赖: server/.env.gs 或 server/.env 中的 EVTRADE_DB_URL
"""
import os
import sys
import glob as glob_mod

# 强制 stdout/stderr 为 UTF-8 (Windows 默认 GBK, 迁移脚本里有 ✓ 等 Unicode)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
SERVER_DIR = os.path.join(PROJECT_ROOT, "server")

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SERVER_DIR)

# 优先 .env.gs，再 .env
try:
    from dotenv import load_dotenv
    for env_name in (".env.gs", ".env"):
        env_path = os.path.join(SERVER_DIR, env_name)
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
            print(f"[load] {env_name}")
            break
except ImportError:
    pass

from sqlalchemy import create_engine, text, inspect

DB_URL = os.environ.get("EVTRADE_DB_URL")
if not DB_URL:
    print("ERROR: EVTRADE_DB_URL not set", file=sys.stderr)
    sys.exit(1)

engine = create_engine(DB_URL, pool_pre_ping=True)

# ─── 1. 检查当前表和行数 ───
print("\n" + "=" * 60)
print("  当前数据库表状态")
print("=" * 60)

inspector = inspect(engine)
tables = inspector.get_table_names()
print(f"共有 {len(tables)} 张表:\n")
for t in sorted(tables):
    with engine.connect() as conn:
        row = conn.execute(text(
            f"SELECT COUNT(*) FROM `{t}`"
        )).first()
    cnt = row[0] if row else 0
    flag = " <-- 空表" if cnt == 0 and t not in ("stocks_legacy",) else ""
    print(f"  {t:<28} {cnt:>6} 行{flag}")

# ─── 2. 按时间顺序运行所有迁移 ───
migration_dir = os.path.join(SERVER_DIR, "migrations")
migration_files = sorted(glob_mod.glob(os.path.join(migration_dir, "2026-*.py")))

print(f"\n" + "=" * 60)
print(f"  运行 {len(migration_files)} 个迁移脚本")
print("=" * 60)

for mf in migration_files:
    fname = os.path.basename(mf)
    print(f"\n--- {fname} ---")
    # 每个迁移是一个独立文件，含 migrate(engine) 或 main()
    # 需要动态加载（不要 import 全路径，会冲突）
    spec = __import__("importlib.util").util.spec_from_file_location(fname, mf)
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if hasattr(mod, "migrate"):
        mod.migrate(engine)
    elif hasattr(mod, "main"):
        mod.main()
    else:
        print(f"  (跳过: 无 migrate() 或 main())")

print("\n" + "=" * 60)
print("  所有迁移完成")
print("=" * 60)

# ─── 3. 最终表状态 ───
print("\n最终表状态:")
with engine.begin() as conn:
    rows = conn.execute(text("""
        SELECT TABLE_NAME, TABLE_ROWS
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME
    """)).fetchall()
    for name, cnt in rows:
        flag = " <-- 空表" if (cnt or 0) == 0 and name != "stocks_legacy" else ""
        print(f"  {name:<28} {cnt or 0:>6} 行{flag}")

engine.dispose()
print("\nDone.")
