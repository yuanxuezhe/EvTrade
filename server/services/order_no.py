"""
order_no.py — 8 位订单序号生成器

保证：
- 8 位数字字符串 '10000001'-'99999999'
- 原子自增（SQLite ≥ 3.21 三步分离 INSERT OR IGNORE + UPDATE + SELECT，函数内 commit）
- 持久化（重启不重置）
- 跨进程/线程安全（SQLite 串行写入）
- 函数内自动 commit（破坏旧"调用方负责 commit"约定）

规范：openspec/specs/rpc-protocol/spec.md REQ-RPC-009
      openspec/changes/2026-06-22-order-no-sqlite-compat (SQLite 3.21.0 兼容)
"""
from sqlalchemy import text
from server.db import SessionLocal
from server.models.orm import OrderNoSeq


def next_order_no(db: SessionLocal) -> str:
    """原子自增，返回 8 位数字字符串。函数内自动 commit（破坏旧约定）。

    实现：三步分离（SQLite ≥ 3.21 兼容方案，2026-06-22 因 Python 3.6.8 自带
    SQLite 3.21.0 不支持 ON CONFLICT...DO UPDATE...RETURNING，从 2026-06-21
    提案的方案 A 降级）：
        1) INSERT OR IGNORE INTO order_no_seq ...  # 兜底初始化
        2) UPDATE order_no_seq SET last_value = last_value + 1 ...  # 自增
        3) SELECT last_value FROM order_no_seq ...  # 读出

    优势：
      1. 兼容当前 SQLite 3.21.0（业务不中断）
      2. 函数内 commit, 消除"调用方漏 commit 导致序号回退"风险
      3. SQLite 串行写入保证并发安全（无应用层锁）

    上限保护：8 位数字最大 99999999，达到上限时拒绝继续分配。

    注意：调用方不需要再 commit (函数已 commit)。
    """
    # 步 1: 兜底初始化 (id=1 不存在时插入 last_value=10000000)
    db.execute(text("""
        INSERT OR IGNORE INTO order_no_seq (id, last_value, updated_at)
        VALUES (1, 10000000, CURRENT_TIMESTAMP)
    """))
    # 步 2: 自增
    db.execute(text("""
        UPDATE order_no_seq
        SET last_value = last_value + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """))
    # 步 3: 读出
    val = db.execute(text(
        "SELECT last_value FROM order_no_seq WHERE id = 1"
    )).scalar()
    if val is None:
        raise RuntimeError("order_no_seq 读取失败")
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
