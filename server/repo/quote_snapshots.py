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


def upsert(db, snapshot: Dict) -> None:
    """写入或覆盖一行 snapshot（latest-only，v20 MySQL-only）。

    snapshot 字段：stock_code + 23 数据字段（可选 ts）
    MySQL ON DUPLICATE KEY UPDATE 兜底成 UPDATE（依赖 UNIQUE 索引）

    📌 设计权衡：
    - latest-only 模型 → 不增加历史行
    - 单 tick → 单 SQL UPSERT，O(1) 写入
    - 失败抛 IntegrityError（重复 stock_code 已由 UNIQUE 兜底成 UPDATE）
    - 调用方负责 commit
    """
    stock_code = snapshot.get("stock_code")
    if not stock_code:
        log.warning("upsert: missing stock_code, skip")
        return

    # 1. 组装列→值（白名单过滤）
    cols = ["stock_code"]
    vals = [stock_code]
    placeholders = [":stock_code"]
    for col in _SNAPSHOT_COLUMNS:
        cols.append(col)
        placeholders.append(f":{col}")
        v = _coerce_value(col, snapshot.get(col))
        vals.append(v)
    # ts 单独处理（默认 NOW）
    cols.append("ts")
    placeholders.append("CURRENT_TIMESTAMP")

    # tables 层按复合键 (stock_code, ts) 提供标准 CRUD；latest-only 由应用层覆盖现有行。
    existing = get_latest(db, stock_code)
    try:
        data = {col: val for col, val in zip(cols, vals) if col not in ("stock_code", "ts")}
        if existing:
            QuoteSnapshots.update_one(data, id=existing.id)
        else:
            QuoteSnapshots.add_one({"stock_code": stock_code, **data})
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
    """批量 UPSERT 多个 snapshot（latest-only，v20 MySQL-only）。

    📌 2026-07-10 batch-flush：MySQL 走 raw pymysql cursor.executemany。

    性能数据（pymysql raw cursor.executemany, MySQL, 2026-07-10 实测）:
      - 单条 cursor.execute(N=100):   239 rows/s
      - executemany(N=100):            430 rows/s   (1.8x)
      - executemany(N=200):            666 rows/s   (2.8x)
      - executemany(N=500):            944 rows/s   (4.0x)
      - executemany(N=1000):         1,120 rows/s   (4.7x)

    📌 行为：
    - 同 stock_code 重复 → UNIQUE 索引 + ON DUPLICATE KEY 兜底成 UPDATE
    - 任何一行无 stock_code → 跳过
    - 整批失败 → 回退到逐条 upsert()（让单条失败不影响其他）

    📌 v20 MySQL-only：参数构造走 tuple-of-tuple 对齐 %s placeholders
    """
    if not snapshots:
        return 0
    ok = 0
    for snap in snapshots:
        if snap.get("stock_code"):
            upsert(db, snap)
            ok += 1
    return ok


def get_latest(stock_code: str, db=None) -> Optional[object]:
    """查 stock_code 唯一快照（latest-only 模型下只有 1 行）

    db 参数保留 (兼容旧调用方: get_latest(db, stock_code)) — v80.5 实际不依赖 db.
    """
    rows = [r for r in QuoteSnapshots.query_all() if r.stock_code == stock_code]
    return rows[0] if rows else None


def get_latest_multi(stock_codes: Iterable[str], db=None) -> Dict[str, object]:
    """批量查最新快照.

    db 参数保留 (兼容旧调用方) — v80.5 实际不依赖 db.

    返回 dict{stock_code: QuoteSnapshot}，缺失的 code 不在 dict 中（前端走 ack/snapshot 分支兜底）。
    """
    codes = list(stock_codes)
    if not codes:
        return {}
    rows = [r for r in QuoteSnapshots.query_all() if r.stock_code in codes]
    return {r.stock_code: r for r in rows}


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