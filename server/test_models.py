"""
test_models.py — 验证 v6 schema（order-pk-by-orderno）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from db import Base, engine, SessionLocal, init_db
from models.orm import (
    Order, Trade, Position, Asset,
    SysStatus, TradingSession, FeeConfig, ReconcileConfig,
    ReconcileReport, QuoteSnapshot, OrderNoSeq,
)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """每个测试用临时 DB"""
    import db as dbmod
    # 强制重置
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


def test_all_tables_created():
    ins = inspect(engine)
    tables = ins.get_table_names()
    expected = {
        "orders", "trades", "positions", "assets",
        "sys_status", "trading_session", "fee_config", "reconcile_config",
        "reconcile_report", "quote_snapshots", "order_no_seq",
    }
    assert expected.issubset(set(tables)), f"缺表: {expected - set(tables)}"


def test_single_row_constraint_fee_config():
    """单行表：用 CheckConstraint(id=1) 保证"""
    db = SessionLocal()
    db.add(FeeConfig(commission_rate=0.0001))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(FeeConfig(id=2, commission_rate=0.0002))
        db.commit()
    db.rollback()
    db.close()


def test_single_row_constraint_reconcile_config():
    db = SessionLocal()
    db.add(ReconcileConfig())
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(ReconcileConfig(id=2))
        db.commit()
    db.rollback()
    db.close()


def test_single_row_constraint_order_no_seq():
    db = SessionLocal()
    db.add(OrderNoSeq())
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(OrderNoSeq(id=2, last_value=20000000))
        db.commit()
    db.rollback()
    db.close()


def test_single_row_constraint_trading_session():
    db = SessionLocal()
    from datetime import time
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(TradingSession(
            id=2,
            morning_start=time(9, 15), morning_end=time(11, 30),
            afternoon_start=time(13, 0), afternoon_end=time(15, 0),
        ))
        db.commit()
    db.rollback()
    db.close()


def test_orders_composite_pk():
    """v6: Order 复合主键 (trd_date, order_no) — 缺一不可

    order_id 出主键后可空;order_no 进主键。
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614", order_no="10000001",
        user_def="CID1",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    # 同 trd_date + order_no 重复 → 必崩
    with pytest.raises(IntegrityError):
        db.add(Order(
            trd_date="20260614", order_no="10000001",  # 同 order_no
            user_def="CID2",
            stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        ))
        db.commit()
    db.rollback()
    db.close()


def test_orders_no_unique_constraints_on_user_def_or_broker_id():
    """v7: 删 uq_orders_client_trd + uq_orders_broker_id 约束
    user_def 同值 + 不同 order_no 可并存（DB 不参与幂等）
    broker order_id 同值 + 不同 order_no 可并存（broker order_id 下单时为空）
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614", order_no="10000001",
        order_id="BROKER-001",
        user_def="SHARED-USER-DEF",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.add(Order(
        trd_date="20260614", order_no="10000002",
        order_id="BROKER-001",  # 同 broker_order_id,不同 order_no → v7 不报错
        user_def="SHARED-USER-DEF",  # 同 user_def → v7 不报错
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()  # v7 应成功,不再 IntegrityError
    assert db.query(Order).filter_by(trd_date="20260614").count() == 2
    db.close()


def test_orders_unique_client_order_id_per_day_removed():
    """v7 删除:不再要求 client_order_id 字段 + UNIQUE 约束
    留作占位,提醒旧约束已废除
    """
    assert True


def test_orders_unique_broker_id_per_day_removed():
    """v7 删除:不再要求 broker order_id + trd_date UNIQUE 约束
    留作占位,提醒旧约束已废除（broker order_id 下单时为空，约束不可靠）
    """
    assert True


def test_orders_order_id_nullable():
    """v6: order_id 字段可空(下单时 broker 还没回报)"""
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614", order_no="10000001",
        order_id=None,  # broker 还没回报
        user_def="CID1",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="48",  # 待报
    ))
    db.commit()
    row = db.query(Order).filter_by(order_no="10000001").first()
    assert row.order_id is None
    db.close()


def test_positions_pk_per_stock():
    """Position 按 stock_code 单 PK，UPSERT 用"""
    db = SessionLocal()
    db.add(Position(stock_code="600030.SH", vol=1000))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Position(stock_code="600030.SH", vol=2000))
        db.commit()
    db.rollback()
    db.close()


def test_assets_single_row_no_pk():
    """Asset v5 起有 PK id=1 + CheckConstraint 限定单行,不再支持"无 PK 多次添加"

    v4 时代 Asset 无 PK,业务侧手动 UPSERT 单行;v5 加 id=1 PK 强制单行。
    """
    db = SessionLocal()
    db.add(Asset(cash=1000.0))  # id=1 default
    db.commit()
    # 同 id 重复 → 必崩 (v5 起)
    with pytest.raises(IntegrityError):
        db.add(Asset(cash=2000.0))  # id=1 default,UNIQUE 冲突
        db.commit()
    db.rollback()
    assert db.query(Asset).count() == 1
    db.close()


def test_sys_status_pk():
    """SysStatus 主键 trd_date（同日重 init 走 upsert）"""
    db = SessionLocal()
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(SysStatus(trd_date="20260614", status="pending"))
        db.commit()
    db.rollback()
    db.close()


def test_quote_snapshot_5_level_book():
    db = SessionLocal()
    q = QuoteSnapshot(
        stock_code="600030.SH", last_price=12.5,
        bid1_price=12.49, ask1_price=12.51, bid1_vol=100, ask1_vol=200,
    )
    db.add(q); db.commit()
    rows = db.query(QuoteSnapshot).all()
    assert rows[0].bid1_price == 12.49
    db.close()
