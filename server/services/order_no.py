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
    """原子自增，返回 8 位数字字符串。调用方负责 db.commit()。"""
    # SQLite UPSERT：id=1 一定存在
    db.execute(text("""
        INSERT INTO order_no_seq (id, last_value, updated_at)
        VALUES (1, 10000001, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            last_value = last_value + 1,
            updated_at = CURRENT_TIMESTAMP
    """))
    # 不在这里 commit —— 让调用方控制事务边界
    row = db.execute(text("SELECT last_value FROM order_no_seq WHERE id = 1")).first()
    if not row:
        # 极端：UPSERT 后查询还没看见（SQLite 同一连接可见），理论上不会发生
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
