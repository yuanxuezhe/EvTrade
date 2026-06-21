"""
test_order_no.py — 验证 8 位订单序号生成器原子自增
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
import asyncio
from db import Base, SessionLocal, init_db
from models.orm import OrderNoSeq, Order


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine_reset())
    init_db()
    yield


def engine_reset():
    from db import engine
    return engine


def test_next_sequential():
    from services.order_no import next_order_no
    db = SessionLocal()
    n1 = next_order_no(db)
    db.commit()
    n2 = next_order_no(db)
    db.commit()
    n3 = next_order_no(db)
    db.commit()
    assert n1 == "10000001"
    assert n2 == "10000002"
    assert n3 == "10000003"
    db.close()


def test_no_duplicates_under_concurrency():
    """并发 100 次调用，必须全部唯一"""
    from services.order_no import next_order_no
    results = []
    errors = []
    lock = asyncio.Lock()

    async def worker():
        db = SessionLocal()
        try:
            for _ in range(10):
                n = next_order_no(db)
                db.commit()
                async with lock:
                    results.append(n)
        except Exception as e:
            errors.append(e)
        finally:
            db.close()

    async def main():
        await asyncio.gather(*[worker() for _ in range(10)])
    asyncio.run(main())

    assert len(errors) == 0, f"错误: {errors}"
    assert len(results) == 100, f"应有 100 个结果，得到 {len(results)}"
    assert len(set(results)) == 100, f"有重复: {set(results) - set(results)}"

    # 全部是 8 位数字
    for n in results:
        assert len(n) == 8
        assert n.isdigit()
        assert 10000000 < int(n) < 10000000 + 200


def test_atomic_no_callback_commit():
    """验证: 调用方回滚后, 序号不回退 (新约定: 函数内 commit)

    旧约定 (调用方负责 commit) 风险:
      n1 = next_order_no(db); db.rollback()  # 撤销 last_value +1
      n2 = next_order_no(db)  # 拿到相同 n1 -> 重复风险

    新约定 (函数内 commit) 保证:
      n1 = next_order_no(db)  # 内部已 commit
      db.rollback()  # 撤销后续 Order INSERT
      n2 = next_order_no(db)  # 拿到 n1+1 (last_value 已持久化)
    """
    from services.order_no import next_order_no
    db = SessionLocal()
    try:
        n1 = next_order_no(db)  # 函数内已 commit
        db.add(Order(order_no=n1, trd_date="20990101", stock_code="000000",
                     order_type="23", price_type=11, price=0.0, volume=0,
                     traded_volume=0, traded_amount=0.0, avg_price=0.0,
                     status="48", status_msg="", order_time="00:00:00"))
        db.commit()  # commit Order (first call)
        # 模拟调用方异常回滚
        n2 = next_order_no(db)  # second call, 函数内 commit
        db.rollback()  # 模拟下游 commit 失败回滚
        n3 = next_order_no(db)  # third call, 序号应继续递增不回退
    finally:
        db.close()

    assert n1 != n2, f"序号应不同: n1={n1}, n2={n2}"
    assert n2 != n3, f"序号应不同: n2={n2}, n3={n3}"
    assert int(n2) == int(n1) + 1, f"应严格 +1: n1={n1}, n2={n2}"
    assert int(n3) == int(n2) + 1, f"应严格 +1: n2={n2}, n3={n3}"


def test_upsert_returns_eight_digit_string():
    """验证: 返回 8 位数字字符串"""
    from services.order_no import next_order_no
    db = SessionLocal()
    try:
        n = next_order_no(db)
    finally:
        db.close()
    assert len(n) == 8
    assert n.isdigit()
    assert int(n) >= 10000001
    assert int(n) <= 99999999
