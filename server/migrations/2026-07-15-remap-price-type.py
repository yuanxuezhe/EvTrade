#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-07-15-remap-price-type.py — 价格类型协议重对齐 (v__)

用户指令 (2026-07-15): "重新设计价格类型方案:
  限价  0: xtconstant.FIX_PRICE
  最新价 1: xtconstant.LATEST_PRICE
  市价  2: xtconstant.MARKET_PEER_PRICE_FIRST"

策略:
  orders.price_type 历史码点 → 新码点 (取整张表 UPDATE, 一次性幂等迁移)
    11  → 0   (旧 "指定价 / 限价"  → 新 "限价")
    14  → 0   (旧 "挂单价 / 对手价" → 新 "限价")
    5   → 1   (旧 "最新价"          → 新 "最新价" 不变)
    44  → 2   (旧 "市价"            → 新 "市价")
    其他 → 原值保留 (已是新协议或未知码点, 不动)

幂等性:
  - UPDATE ... WHERE price_type IN (11,14) AND 已迁移过 = 0 行才返回 affected
  - 第 N 次执行只会匹配剩余未迁移的行, 重复运行 = no-op
  - 末尾做完整性校验: 任何 price_type 不在 {0,1,2} 都报错 (说明还有未识别的码点)

依赖:
  server/.env 含 EVTRADE_DB_URL (v20 MySQL-only 强制)

用法:
  python3 server/migrations/2026-07-15-remap-price-type.py
"""
import os
import sys

# 确保项目根在 sys.path（server/.env 的 load_dotenv 需 server 目录在 path）
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SERVER_DIR)

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(SERVER_DIR, ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine

# v20 MySQL-only 强制: 显式读 EVTRADE_DB_URL
DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (v20 MySQL-only permanent standard). "
        "Set it in server/.env"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"Only MySQL is supported (v20 permanent standard). Got URL: {DATABASE_URL[:80]!r}"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ─────────────── 映射表 ───────────────
# 新码点 = 0 (限价) / 1 (最新价) / 2 (市价)
REMAP = {
    11: 0,   # 旧 指定价/限价   → 新 限价
    14: 0,   # 旧 挂单价/对手价 → 新 限价 (UI 上原 14 按钮 label 也叫"限价")
    5:  1,   # 旧 最新价        → 新 最新价
    44: 2,   # 旧 市价          → 新 市价
}


def _info_schema_table_exists(conn, table_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = :t
         LIMIT 1
    """), {"t": table_name}).first()
    return row is not None


def _info_schema_column_exists(conn, table_name: str, column_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME   = :t
           AND COLUMN_NAME  = :c
         LIMIT 1
    """), {"t": table_name, "c": column_name}).first()
    return row is not None


def main():
    with engine.begin() as conn:
        # 0. 前置检查
        if not _info_schema_table_exists(conn, "orders"):
            raise RuntimeError(
                "[migrate] orders 表不存在, 请先 init_db 创建表结构"
            )
        if not _info_schema_column_exists(conn, "orders", "price_type"):
            raise RuntimeError(
                "[migrate] orders.price_type 列不存在"
            )

        # 1. 迁移前快照: 按 price_type 分组统计
        before = conn.execute(text("""
            SELECT price_type, COUNT(*) AS cnt
              FROM orders
             GROUP BY price_type
             ORDER BY price_type
        """)).all()
        print("[before] orders.price_type 分布:")
        total = 0
        for pt, cnt in before:
            print(f"  {int(pt):>3} : {cnt} 行")
            total += int(cnt)
        print(f"  -- 合计 {total} 行 --")

        # 2. 执行迁移: 逐个旧码点 UPDATE (幂等: 已迁移的行不匹配, 第 N 次跑是 no-op)
        remap_log = []
        for old, new in REMAP.items():
            result = conn.execute(text("""
                UPDATE orders
                   SET price_type = :new
                 WHERE price_type = :old
            """), {"old": old, "new": new})
            affected = result.rowcount
            remap_log.append((old, new, affected))
            if affected:
                print(f"[remap] {old} → {new}: {affected} 行")
            else:
                print(f"[remap] {old} → {new}: 0 行 (no-op, 已迁移或不存在)")

        # 3. 迁移后快照
        after = conn.execute(text("""
            SELECT price_type, COUNT(*) AS cnt
              FROM orders
             GROUP BY price_type
             ORDER BY price_type
        """)).all()
        print("\n[after] orders.price_type 分布:")
        for pt, cnt in after:
            print(f"  {int(pt):>3} : {cnt} 行")

        # 4. 完整性校验: 不允许存在 {0,1,2} 之外的码点
        unexpected = [int(pt) for pt, cnt in after if int(pt) not in (0, 1, 2)]
        if unexpected:
            raise RuntimeError(
                f"[verify FAILED] orders.price_type 仍存在未识别码点: {unexpected}\n"
                f"这些码点不属于新协议 0/1/2, 需要手动处理或扩展 REMAP 表后再重跑"
            )
        print("\n[verify OK] 所有 price_type 均在 {0,1,2} 新协议码点范围内")

        # 5. 总数对账
        total_after = sum(int(cnt) for _pt, cnt in after)
        if total_after != total:
            raise RuntimeError(
                f"[verify FAILED] 迁移前 {total} 行 vs 迁移后 {total_after} 行, "
                f"行数不一致"
            )
        print(f"[verify OK] 总行数 {total_after} 一致 (迁移前 = 迁移后)")

        # 6. 汇总
        total_migrated = sum(c for _o, _n, c in remap_log)
        print(f"\n[summary] 共迁移 {total_migrated} 行:")
        for old, new, c in remap_log:
            print(f"  {old} → {new}: {c} 行")

    engine.dispose()
    print(f"\n[OK] orders.price_type 已重对齐到 xtconstant 协议 0/1/2")


if __name__ == "__main__":
    main()