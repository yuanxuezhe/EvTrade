#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_stocks_from_idb.py — 从前端 IndexedDB 导出的 JSON 批量 upsert 到 stocks 表

用法:
  1. 在浏览器控制台执行（打开 EvTrade 前端页面）:
     const db = await indexedDB.open('EvTrade-stocks', 2);
     const tx = db.transaction('stocks', 'readonly');
     const store = tx.objectStore('stocks');
     const data = await store.getAll();
     copy(JSON.stringify(data));
     db.close();
  2. 把输出的内容保存为 data/stocks_from_idb.json
  3. 运行本脚本:
     uv run python scripts/sync_stocks_from_idb.py

或直接指定文件:
  uv run python scripts/sync_stocks_from_idb.py --file /path/to/stocks.json
"""
import argparse
import io
import json
import os
import sys

# Fix GBK encoding on Windows
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
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
            break
except ImportError:
    pass

from sqlalchemy import create_engine, text

DB_URL = os.environ.get("EVTRADE_DB_URL")
if not DB_URL:
    print("ERROR: EVTRADE_DB_URL not set", file=sys.stderr)
    sys.exit(1)

engine = create_engine(DB_URL, pool_pre_ping=True)


def short_name_from(stock_name):
    """生成 short_name (拼音首字母小写)"""
    if not stock_name:
        return ""
    # 简单方案：直接用 stock_name 前2个字符（中文名简称）
    # PDF 里的 short_name 实际就是拼音首字母，但不用 pypinyin 依赖
    # 前端存的数据里已有 short_name，直接保留
    return ""


def main():
    parser = argparse.ArgumentParser(description="Sync stocks from IndexedDB export")
    parser.add_argument("--file", default=os.path.join(PROJECT_ROOT, "data", "stocks_from_idb.json"),
                        help="Path to exported stocks JSON file")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ 文件不存在: {args.file}")
        print()
        print("请先从浏览器控制台导出:")
        print("  const db = await indexedDB.open('EvTrade-stocks', 2);")
        print("  const tx = db.transaction('stocks', 'readonly');")
        print("  const store = tx.objectStore('stocks');")
        print("  const data = await store.getAll();")
        print("  copy(JSON.stringify(data));")
        print("  db.close();")
        print()
        print("然后把复制的内容保存为:")
        print(f"  {args.file}")
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8") as f:
        stocks = json.load(f)

    if not isinstance(stocks, list):
        print("❌ JSON 格式错误：顶层必须是数组")
        sys.exit(1)

    print(f"📋 读取 {len(stocks)} 只证券数据")

    # Check current DB state
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT COUNT(*) FROM `stocks`")).fetchone()[0]
    print(f"📊 当前 stocks 表: {existing} 行")

    # Fields we accept from IDB export
    VALID_FIELDS = {
        'stock_code', 'stock_name', 'sector',
        'is_t0_able', 'min_buy_qty', 'trade_unit',
        'short_name', 'stktype', 'scale',
    }

    # Build batch INSERT ... ON DUPLICATE KEY UPDATE
    # 5500+ rows, batch size 500 per transaction
    BATCH_SIZE = 500
    inserted = 0
    updated = 0
    errors = 0

    for batch_start in range(0, len(stocks), BATCH_SIZE):
        batch = stocks[batch_start:batch_start + BATCH_SIZE]
        print(f"\n  处理批次 {batch_start // BATCH_SIZE + 1} (第 {batch_start + 1}-{min(batch_start + BATCH_SIZE, len(stocks))} 只)...", end=" ", flush=True)

        with engine.begin() as conn:
            for stock in batch:
                try:
                    code = stock.get('stock_code')
                    if not code:
                        errors += 1
                        continue

                    # Build INSERT ... ON DUPLICATE KEY UPDATE
                    fields = []
                    values = {}
                    for k in VALID_FIELDS:
                        if k in stock and k != 'stock_code':
                            v = stock[k]
                            # Handle None/empty gracefully
                            if k == 'sector' and (v is None or v == ''):
                                values[k] = None
                            elif k == 'short_name' and (v is None or v == ''):
                                values[k] = None
                            elif k in ('is_t0_able',):
                                values[k] = 1 if v else 0
                            else:
                                values[k] = v if v is not None else 0

                    # Always include stock_code + required fields with defaults
                    values.setdefault('stock_name', '')
                    values.setdefault('sector', None)
                    values.setdefault('is_t0_able', 0)
                    values.setdefault('min_buy_qty', 100)
                    values.setdefault('trade_unit', 1)
                    values.setdefault('short_name', stock.get('short_name'))
                    values.setdefault('stktype', 0)
                    values.setdefault('scale', 2)

                    col_list = ", ".join(f"`{k}`" for k in values.keys())
                    val_list = ", ".join(f":{k}" for k in values.keys())
                    update_list = ", ".join(
                        f"`{k}` = VALUES(`{k}`)"
                        for k in values.keys() if k != 'stock_code'
                    )

                    sql = text(
                        f"INSERT INTO `stocks` ({col_list}) VALUES ({val_list}) "
                        f"ON DUPLICATE KEY UPDATE {update_list}"
                    )

                    # Add created_at / updated_at if missing
                    values['created_at'] = 'NOW()'  # handled by DB default
                    values['updated_at'] = 'NOW()'  # handled by DB default

                    # Remove the NOW() placeholders — let DB handle defaults
                    values.pop('created_at', None)
                    values.pop('updated_at', None)
                    # Instead explicitly set updated_at
                    values['updated_at'] = None  # will be filled by upsert_one logic

                    conn.execute(sql, values)

                    # Check if it was insert or update via ROW_COUNT()
                    rc_row = conn.execute(text("SELECT ROW_COUNT() AS rc")).fetchone()
                    rc = rc_row[0] if rc_row else 0
                    # ROW_COUNT(): 1 = inserted, 2 = updated, 0 = unchanged
                    if rc == 1:
                        inserted += 1
                    elif rc == 2:
                        updated += 1
                    else:
                        errors += 1

                except Exception as e:
                    print(f"\n  ❌ {stock.get('stock_code', '?')}: {e}", file=sys.stderr)
                    errors += 1

        print(f"✅")

    # Final count
    with engine.connect() as conn:
        final_count = conn.execute(text("SELECT COUNT(*) FROM `stocks`")).fetchone()[0]

    print(f"\n{'=' * 50}")
    print(f"完成! 总计 {len(stocks)} 只:")
    print(f"  新增: {inserted}")
    print(f"  更新: {updated}")
    print(f"  错误: {errors}")
    print(f"  stocks 表现有: {final_count} 行")
    print(f"{'=' * 50}")

    engine.dispose()


if __name__ == "__main__":
    main()
