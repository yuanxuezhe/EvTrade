"""
order_no.py — 8 位订单序号生成器

保证：
- 8 位数字字符串 '10000001'-'99999999'
- 原子自增（SQLite ≥ 3.35 单语句 INSERT ... ON CONFLICT DO UPDATE ... RETURNING）
- 持久化（重启不重置）
- 跨进程/线程安全（SQLite 串行写入）
- 函数内自动 commit（破坏旧"调用方负责 commit"约定）

规范：openspec/changes/2026-06-21-order-no-atomic-upsert/spec-deltas/rpc-protocol.md
      REQ-RPC-009
"""
from sqlalchemy import text
from db import SessionLocal
from models.orm import OrderNoSeq


def next_order_no(db: SessionLocal) -> str:
    """原子自增，返回 8 位数字字符串。函数内自动 commit（破坏旧约定）。

    实现：单语句 UPSERT（SQLite ≥ 3.35）
        INSERT INTO order_no_seq (id, last_value, updated_at)
        VALUES (1, 10000001, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            last_value = last_value + 1,
            updated_at = CURRENT_TIMESTAMP
        RETURNING last_value

    优势 vs 旧 3 步方案:
      1. 单语句原子 (SQLite 串行写入保证, 无应用层锁)
      2. 函数内 commit, 消除"调用方漏 commit 导致序号回退"风险
      3. docstring 与实现一致 (旧 docstring 撒谎说 UPSERT 但实现是 3 步)

    上限保护：8 位数字最大 99999999，达到上限时拒绝继续分配。

    注意：调用方不需要再 commit (函数已 commit)。
    """
    row = db.execute(text("""
        INSERT INTO order_no_seq (id, last_value, updated_at)
        VALUES (1, 10000001, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            last_value = last_value + 1,
            updated_at = CURRENT_TIMESTAMP
        RETURNING last_value
    """)).first()
    if not row:
        raise RuntimeError("order_no_seq UPSERT 失败")
    val = row[0]
    if val >= 99999999:
        raise RuntimeError(
            f"order_no 已达上限 ({val})，请手动扩容或迁移新序号段"
        )
    db.commit()
    return str(val)


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
