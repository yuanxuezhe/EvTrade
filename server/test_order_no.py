"""
test_order_no.py — 验证 8 位订单序号生成器原子自增
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
import asyncio
from db import Base, SessionLocal, init_db
from models.orm import OrderNoSeq


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
