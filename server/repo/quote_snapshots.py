"""
repo/quote_snapshots.py — quote_snapshots 表仓库（2026-07-09 完整实现）

📌 设计：latest-only 模型（每 stock_code 1 行，UPSERT 覆盖）
📌 ORM 列名（server/models/orm.py:295-334）：
   - open_price / high_price / low_price / prev_close (Float)
   - last_price / amount (Float)
   - volume / bid*_vol / ask*_vol (Integer，手/股数)
   - bid1_price .. bid5_price (Float, 买价 1=最高买 .. 5=最低买)
   - ask1_price .. ask5_price (Float, 卖价 1=最低卖 .. 5=最高卖)
📌 跨方言 UPSERT（v20 MySQL-only 永久标准）:
   - MySQL : INSERT ... ON DUPLICATE KEY UPDATE ...
📌 表已加 UNIQUE 约束：migration 2026-07-09-add-quote-snapshots-unique.py
📌 应用层调用点：server.services.strategy.quote_consumer._save_snapshot
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

from server.tables.quote_snapshots import QuoteSnapshots

# Backward-compatible alias for callers that import the table symbol.
QuoteSnapshot = QuoteSnapshots

log = logging.getLogger(__name__)


# ─────────────── ORM 列名白名单（防止外部传入任意字段拼 SQL 注入） ───────────────

# 23 字段：除 stock_code/ts 外的所有数据字段
_SNAPSHOT_COLUMNS: List[str] = [
    "last_price", "open_price", "high_price", "low_price", "prev_close",
    "volume", "amount",
    "bid1_price", "bid1_vol", "bid2_price", "bid2_vol",
    "bid3_price", "bid3_vol", "bid4_price", "bid4_vol",
    "bid5_price", "bid5_vol",
    "ask1_price", "ask1_vol", "ask2_price", "ask2_vol",
    "ask3_price", "ask3_vol", "ask4_price", "ask4_vol",
    "ask5_price", "ask5_vol",
]


def _coerce_value(col: str, v) -> object:
    """按 ORM 列类型做类型转换（GBK 解码后字符串需转 Float/Int）"""
    if v is None or v == "":
        # 缺失字段 → 0.0/0（ORM default）
        return 0 if col.endswith("_vol") or col == "volume" else 0.0
    try:
        if col.endswith("_vol") or col == "volume":
            return int(float(v))
        return float(v)
    except (ValueError, TypeError):
        return 0 if col.endswith("_vol") or col == "volume" else 0.0


def _build_snapshot_sql(data: Dict) -> str:
    """v111: 原子 UPSERT SQL, 不依赖预查 existing

    📌 取代 v84.4 之前 "get_latest → if existing: update else: add" 的双段式:
       - 之前必须 add_one (会跳过 id 列) + _get_required_columns 自动填 NOT NULL 列
         → id 列被填了 0 进 INSERT（v111 bug: 没跳过 auto_increment 列）
       - 之前 + query_by_fields 在新连接 REPEATABLE READ 看不到刚 commit 的行
         → get_latest 误返 None → 走 add_one → 撞 stock_code UNIQUE
    📌 修法: 直接 INSERT … ON DUPLICATE KEY UPDATE 走 stock_code UNIQUE 索引,
       原子 + race-safe + 不依赖 get_latest
    """
    cols = ["`stock_code`"] + [f"`{c}`" for c in _SNAPSHOT_COLUMNS] + ["`ts`"]
    placeholders = [":stock_code"] + [f":{c}" for c in _SNAPSHOT_COLUMNS] + ["CURRENT_TIMESTAMP"]
    # UPDATE 子句: 全部数据列 + ts 重置为 NOW
    parts = [f"`{c}` = VALUES(`{c}`)" for c in _SNAPSHOT_COLUMNS] + ["`ts` = VALUES(`ts`)"]
    sql = (
        f"INSERT INTO quote_snapshots ({', '.join(cols)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON DUPLICATE KEY UPDATE {', '.join(parts)}"
    )
    return sql


def upsert(db, snapshot: Dict) -> None:
    """写入或覆盖一行 snapshot（latest-only，MySQL only）。

    v111 重写: 用 INSERT … ON DUPLICATE KEY UPDATE 原子 UPSERT，
    不再 get_latest → if/else。两层修:
    1) 消除 race (REPEATABLE READ 看不到刚 commit 行)
    2) 消除 _get_required_columns 把 id 列填 0 进 INSERT 的 bug

    📌 调用方负责 commit
    """
    stock_code = snapshot.get("stock_code")
    if not stock_code:
        log.warning("upsert: missing stock_code, skip")
        return

    params = {"stock_code": stock_code}
    for col in _SNAPSHOT_COLUMNS:
        params[col] = _coerce_value(col, snapshot.get(col))

    sql = _build_snapshot_sql(params)
    try:
        db.execute(text(sql), params)
    except Exception as e:
        log.exception("quote_snapshots.upsert failed stock=%s: %s", stock_code, e)
        raise


def _build_batch_sql(cols: List[str]) -> str:
    """构造 MySQL 批量 UPSERT SQL（v20 MySQL-only 永久标准）。

    📌 2026-07-10 batch-flush + v20 MySQL-only：
       - 占位符走 `%s`（pymysql cursor.executemany tuple-of-tuple）
       - ts 由 SQL 字符串直接写 CURRENT_TIMESTAMP（migration schema ts 列无 DEFAULT，
         不能用占位符参数化）
       - 同 stock_code 重复 → ON DUPLICATE KEY UPDATE 兜底（依赖 UNIQUE 索引）

    性能收益（pymysql cursor.executemany vs 单条 cursor.execute loop, 2026-07-10 实测）:
      - loop N=100:               239 rows/s (单 commit)
      - executemany N=100:        430 rows/s   (1.8x)
      - executemany N=200:        666 rows/s   (2.8x)
      - executemany N=500:        944 rows/s   (4.0x)
      - executemany N=1000:     1,120 rows/s   (4.7x)
    """
    cols_no_ts = [c for c in cols if c != "ts"]
    n_cols = len(cols_no_ts)
    insert_cols_clause = ",".join(cols_no_ts) + ",ts"
    placeholders = ",".join(["%s"] * n_cols)
    values_clause = f"{placeholders},CURRENT_TIMESTAMP"
    update_parts = (
        ",".join([f"{c}=VALUES({c})" for c in cols_no_ts if c != "stock_code"])
        + ",ts=CURRENT_TIMESTAMP"
    )
    return (
        f"INSERT INTO quote_snapshots ({insert_cols_clause}) "
        f"VALUES ({values_clause}) "
        f"ON DUPLICATE KEY UPDATE {update_parts}"
    )


def upsert_batch(db, snapshots: List[Dict]) -> int:
    """批量 UPSERT 多个 snapshot（latest-only，MySQL only）。

    📌 v111: 走真正的 executemany 批量 + stock_code UNIQUE 索引 ON DUPLICATE KEY
       单 SQL 一次插入 = O(1) round-trip / row (pymysql vs N round-trips)
       之前 v84.4 的循环单条是规避 IntegrityError 的兜底;
       现在原子 UPSERT 不会报 IntegrityError, 直接 executemany

    性能 (pymysql raw cursor.executemany, MySQL, 2026-07-10 实测):
      - 单条 cursor.execute(N=100):   239 rows/s
      - executemany(N=100):            430 rows/s   (1.8x)
      - executemany(N=200):            666 rows/s   (2.8x)
      - executemany(N=500):            944 rows/s   (4.0x)
      - executemany(N=1000):         1,120 rows/s   (4.7x)
    """
    if not snapshots:
        return 0
    valid_snaps = [s for s in snapshots if s.get("stock_code")]
    if not valid_snaps:
        return 0
    try:
        # v111.1: ts 也进 VALUES (timestamp NOT NULL, 不能漏)
        #   INSERT 用 %s (current_ts 是 SQL 字面量, 不走 pymysql param)
        col_names = ["stock_code"] + _SNAPSHOT_COLUMNS  # 26 + 1 stock_code
        placeholders = ", ".join(["%s"] * len(col_names)) + ", CURRENT_TIMESTAMP"
        update_parts = [f"`{col}`=VALUES(`{col}`)" for col in _SNAPSHOT_COLUMNS]
        update_parts.append("`ts`=VALUES(`ts`)")  # ts 占位符在 VALUES 里, UPDATE 时也置 NOW
        sql = (
            f"INSERT INTO quote_snapshots ({', '.join(f'`{c}`' for c in col_names)}, `ts`) "
            f"VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {', '.join(update_parts)}"
        )
        rows = []
        for snap in valid_snaps:
            row = []
            for col in col_names:
                if col == "stock_code":
                    row.append(snap.get("stock_code"))
                else:
                    row.append(_coerce_value(col, snap.get(col)))
            rows.append(tuple(row))
        cursor = db.connection().connection.cursor()
        try:
            cursor.executemany(sql, rows)
        finally:
            cursor.close()
        db.commit()  # pymysql autocommit=False, 手动 commit
        return len(rows)
    except Exception as e:
        log.exception("upsert_batch failed, fallback single: %s", e)
        ok = 0
        for snap in valid_snaps:
            try:
                upsert(db, snap)
                ok += 1
            except Exception:
                pass
        return ok


def get_latest(stock_code: str, db=None) -> Optional[object]:
    """查 stock_code 唯一快照（latest-only 模型下只有 1 行）

    db 参数保留 (兼容旧调用方: get_latest(db, stock_code)) — v80.5 实际不依赖 db.

    v84.4 BUG 修复: 之前用 QuoteSnapshots.query_all() (全表扫 5万行) + Python filter,
      不仅 O(N) 慢, 还因为 _execute_select 用新连接 (REPEATABLE READ) 看不到同事务
      内刚 INSERT 但未 commit 的数据, 导致 add_one INSERT 触发 UNIQUE 冲突 IntegrityError.
    修法: 用 query_by_fields 直接 WHERE stock_code=? (UNIQUE 索引 → O(logN))
    """
    rows = QuoteSnapshots.query_by_fields({"stock_code": stock_code}, limit=1)
    return rows[0] if rows else None


def get_latest_multi(stock_codes: Iterable[str], db=None) -> Dict[str, object]:
    """批量查最新快照.

    db 参数保留 (兼容旧调用方) — v80.5 实际不依赖 db.

    返回 dict{stock_code: QuoteSnapshot}，缺失的 code 不在 dict 中（前端走 ack/snapshot 分支兜底）。

    v84.4: query_by_fields 当前只支持 = 等值, 不支持 IN tuple. 循环单查:
      UNIQUE 索引 → 单查 O(logN), 100 个 codes 总计 O(100*logN) 远小于 query_all() 5万行扫表.
    """
    codes = list(stock_codes)
    if not codes:
        return {}
    out = {}
    for code in codes:
        rows = QuoteSnapshots.query_by_fields({"stock_code": code}, limit=1)
        if rows:
            out[code] = rows[0]
    return out


def to_dict(snap) -> Dict:
    """ORM 对象 → JSON 序列化友好 dict（供 ws 推送 snapshot 帧）"""
    if snap is None:
        return {}
    return {
        "stock_code": snap.stock_code,
        "last_price": snap.last_price,
        "open_price": snap.open_price,
        "high_price": snap.high_price,
        "low_price": snap.low_price,
        "prev_close": snap.prev_close,
        "volume": snap.volume,
        "amount": snap.amount,
        "bid1_price": snap.bid1_price, "bid1_vol": snap.bid1_vol,
        "bid2_price": snap.bid2_price, "bid2_vol": snap.bid2_vol,
        "bid3_price": snap.bid3_price, "bid3_vol": snap.bid3_vol,
        "bid4_price": snap.bid4_price, "bid4_vol": snap.bid4_vol,
        "bid5_price": snap.bid5_price, "bid5_vol": snap.bid5_vol,
        "ask1_price": snap.ask1_price, "ask1_vol": snap.ask1_vol,
        "ask2_price": snap.ask2_price, "ask2_vol": snap.ask2_vol,
        "ask3_price": snap.ask3_price, "ask3_vol": snap.ask3_vol,
        "ask4_price": snap.ask4_price, "ask4_vol": snap.ask4_vol,
        "ask5_price": snap.ask5_price, "ask5_vol": snap.ask5_vol,
        "ts": snap.ts.isoformat() if snap.ts else None,
    }


__all__ = [
    "upsert",
    "get_latest",
    "get_latest_multi",
    "to_dict",
]