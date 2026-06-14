"""
test_models.py — 验证 v4 11 张新表
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from db import Base, engine, SessionLocal, init_db
from models.orm import (
    Order, Trade, Position, Asset,
    TradingDay, TradingSession, FeeConfig, ReconcileConfig,
    ReconcileReport, QuoteSnapshot, OrderNoSeq,
)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """每个测试用临时 DB"""
    import importlib, db as dbmod
    # 强制重置
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


def test_all_tables_created():
    ins = inspect(engine)
    tables = ins.get_table_names()
    expected = {
        "orders", "trades", "positions", "assets",
        "trading_day", "trading_session", "fee_config", "reconcile_config",
        "reconcile_report", "quote_snapshots", "order_no_seq",
    }
    assert expected.issubset(set(tables)), f"缺表: {expected - set(tables)}"


def test_single_row_constraint_assets():
    db = SessionLocal()
    db.add(Asset(TRD_DATE="20260614", cash=1000.0))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Asset(id=2, TRD_DATE="20260615", cash=2000.0))
        db.commit()
    db.rollback()
    db.close()


def test_single_row_constraint_fee_config():
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


def test_orders_unique_order_id():
    db = SessionLocal()
    db.add(Order(
        order_id="OID1", client_order_id="CID1", order_no="10000001",
        order_remark="", TRD_DATE="20260614", stock_code="600030.SH",
        order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Order(
            order_id="OID1", client_order_id="CID2", order_no="10000002",
            order_remark="", TRD_DATE="20260614", stock_code="600030.SH",
            order_type="23", price_type=11, price=12.5, volume=100,
        ))
        db.commit()
    db.rollback()
    db.close()


def test_orders_unique_client_order_id_idempotency():
    """幂等号是下表的核心：重发同 client_order_id 必崩"""
    db = SessionLocal()
    db.add(Order(
        order_id="OID1", client_order_id="CID-SAME", order_no="10000001",
        order_remark="", TRD_DATE="20260614", stock_code="600030.SH",
        order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Order(
            order_id="OID2", client_order_id="CID-SAME", order_no="10000002",
            order_remark="", TRD_DATE="20260614", stock_code="600030.SH",
            order_type="23", price_type=11, price=12.5, volume=100,
        ))
        db.commit()
    db.rollback()
    db.close()


def test_orders_unique_order_no():
    """order_no 8 位序号也是 UNIQUE"""
    db = SessionLocal()
    db.add(Order(
        order_id="OID1", client_order_id="CID1", order_no="10000001",
        order_remark="", TRD_DATE="20260614", stock_code="600030.SH",
        order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Order(
            order_id="OID2", client_order_id="CID2", order_no="10000001",
            order_remark="", TRD_DATE="20260614", stock_code="600030.SH",
            order_type="23", price_type=11, price=12.5, volume=100,
        ))
        db.commit()
    db.rollback()
    db.close()


def test_positions_unique_per_day():
    """持仓按 (TRD_DATE, stock_code) 唯一"""
    db = SessionLocal()
    db.add(Position(TRD_DATE="20260614", stock_code="600030.SH", total=1000))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Position(TRD_DATE="20260614", stock_code="600030.SH", total=2000))
        db.commit()
    db.rollback()
    db.close()


def test_assets_unique_per_day():
    """资金按 TRD_DATE 唯一"""
    db = SessionLocal()
    db.add(Asset(TRD_DATE="20260614", cash=1000))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Asset(TRD_DATE="20260614", cash=2000))
        db.commit()
    db.rollback()
    db.close()


def test_trading_day_state():
    db = SessionLocal()
    db.add(TradingDay(current_date="20260614", status="active"))
    db.commit()
    rows = db.query(TradingDay).all()
    assert len(rows) == 1
    assert rows[0].status == "active"
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
