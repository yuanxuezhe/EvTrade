#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_missing_data.py — 初始化缺失的基础数据

1. order_no_seq: 插入初始序列行 (id=1, last_value=0)
2. sys_status: 插入今日初始系统状态
3. stocks: 触发全 A 股同步（从 sina 拉代码列表 + eastmoney 爬虫）
"""
import os
import sys
import io

# Fix GBK encoding on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
SERVER_DIR = os.path.join(PROJECT_ROOT, "server")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SERVER_DIR)

# Load .env
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

from sqlalchemy import create_engine, text

DB_URL = os.environ.get("EVTRADE_DB_URL")
if not DB_URL:
    print("ERROR: EVTRADE_DB_URL not set", file=sys.stderr)
    sys.exit(1)

engine = create_engine(DB_URL, pool_pre_ping=True)


def seed_order_no_seq():
    """初始化订单号序列"""
    print("\n" + "=" * 50)
    print("1. Seed order_no_seq")
    print("=" * 50)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT `id`, `last_value` FROM `order_no_seq` LIMIT 1")).first()
        if row:
            print(f"  order_no_seq 已有数据: id={row[0]}, last_value={row[1]}, 跳过")
        else:
            conn.execute(text(
                "INSERT INTO `order_no_seq` (`id`, `last_value`, `updated_at`) VALUES (1, 0, NOW())"
            ))
            print("  ✅ 已初始化 order_no_seq (id=1, last_value=0)")


def seed_sys_status():
    """初始化今日系统状态"""
    print("\n" + "=" * 50)
    print("2. Seed sys_status")
    print("=" * 50)
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT id, trd_date, status FROM sys_status ORDER BY id DESC LIMIT 1"
        )).first()
        if row:
            print(f"  sys_status 已有数据: id={row[0]}, trd_date={row[1]}, status={row[2]}, 跳过")
        else:
            conn.execute(text(
                "INSERT INTO sys_status (id, trd_date, status, is_half_day, initialized_at, initialized_by, created_at, updated_at) "
                "VALUES (1, CURDATE(), 'open', 0, NOW(), 'system', NOW(), NOW())"
            ))
            print("  ✅ 已初始化 sys_status (id=1, today, status=open)")


def sync_stocks():
    """同步全 A 股 stocks 数据"""
    print("\n" + "=" * 50)
    print("3. Sync stocks (full A-share)")
    print("=" * 50)

    with engine.connect() as conn:
        stock_count = conn.execute(text("SELECT COUNT(*) FROM stocks")).first()[0]
        print(f"  当前 stocks 表: {stock_count} 行")
        if stock_count > 100:
            print(f"  stocks 已有 {stock_count} 行数据，跳过全量同步")
            return

    # Use async sync via the existing sync infrastructure
    print("  开始全 A 股同步 (sina_list → eastmoney → stocks)...")
    print("  ⚠️  注意: 全量同步约 5500+ 只股票，每只间隔 0.5s，预计 45-50 分钟")
    print("  建议: 在 FastAPI 启动后，通过 POST /api/sync/stocks 触发")
    print("  或: 直接在终端运行 python server/crawler/sources/sina_list.py 测试 sina 接口")

    # Try a quick sync with sina_list
    try:
        from server.crawler.sources.sina_list import fetch_all_a_codes
        codes = fetch_all_a_codes(use_cache=True)
        print(f"  ✅ sina_list 获取 {len(codes)} 只股票代码")
        print(f"  缓存已保存，后续通过 POST /api/sync/stocks 完成全量同步")
    except Exception as e:
        print(f"  ⚠️  sina_list 获取失败: {e}")
        print("  请检查网络连接，或手动运行: python server/crawler/sources/sina_list.py")


if __name__ == "__main__":
    seed_order_no_seq()
    seed_sys_status()
    sync_stocks()

    # Final status
    print("\n" + "=" * 50)
    print("最终表数据状态")
    print("=" * 50)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT TABLE_NAME, TABLE_ROWS
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME NOT IN ('stocks_legacy')
            ORDER BY TABLE_NAME
        """)).fetchall()
        for name, cnt in rows:
            flag = " <-- 空表" if (cnt or 0) == 0 else ""
            print(f"  {name:<28} {cnt or 0:>6} 行{flag}")

    engine.dispose()
    print("\n✅ Seed 完成")
