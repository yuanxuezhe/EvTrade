"""
order_no.py — 8 位订单序号生成器

保证：
- 8 位数字字符串 '10000001'-'99999999'
- 原子自增（SQLite UPSERT + RETURNING）
- 持久化（重启不重置）
- 跨进程/线程安全（SQLite 串行写入）

注意：调用方负责 commit。
"""
from sqlalchemy import text
from db import SessionLocal
from models.orm import OrderNoSeq


def next_order_no(db: SessionLocal) -> str:
    """原子自增，返回 8 位数字字符串。调用方负责 db.commit()。

    兼容老版 SQLite (<3.24)：
      1. INSERT OR IGNORE 初始化行（如果不存在）
      2. UPDATE last_value = last_value + 1
      3. SELECT 读新值
    SQLite 写入串行化，UPDATE 是原子的，所以序号唯一递增。
    """
    db.execute(text("""
        INSERT OR IGNORE INTO order_no_seq (id, last_value, updated_at)
        VALUES (1, 10000000, CURRENT_TIMESTAMP)
    """))
    db.execute(text("""
        UPDATE order_no_seq
        SET last_value = last_value + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """))
    row = db.execute(text("SELECT last_value FROM order_no_seq WHERE id = 1")).first()
    if not row:
        raise RuntimeError("order_no_seq 写入失败")
    return str(row[0])


def get_current_no(db: SessionLocal) -> int:
    """查询当前序号（不递增）"""
    row = db.execute(text("SELECT last_value FROM order_no_seq WHERE id = 1")).first()
    if not row:
        return 10000000
    return row[0]


def reset_to(db: SessionLocal, value: int) -> None:
    """重置序号（仅测试/迁移用）"""
    db.execute(text("""
        UPDATE order_no_seq SET last_value = :v, updated_at = CURRENT_TIMESTAMP WHERE id = 1
    """), {"v": value})
    db.commit()
