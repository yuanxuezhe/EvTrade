"""
test_push_handlers.py — 验证 4 类 push 落库
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from datetime import datetime
from db import Base, engine, init_db, SessionLocal
from models.orm import Order, Trade, Position, Asset, TradingDay
from services.push_handlers import handle_push


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    db.add(TradingDay(current_date="20260614", status="active"))
    db.commit()
    db.close()
    yield


# ──── ord_cfm ────

def test_ord_cfm_updates_existing_order_by_remark():
    """通过 order_remark (本地 order_no) 匹配本地 Order"""
    db = SessionLocal()
    db.add(Order(
        order_id="local-10000001", client_order_id="CID-1", order_no="10000001",
        order_remark="10000001", TRD_DATE="20260614",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="48",  # 待报
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "BROKER-OID-1",
        "order_remark": "10000001",
        "status": "49",          # 已报
        "traded_volume": 0,
        "traded_amount": 0,
        "avg_price": 0,
    }, ts="20260614 09:30:01")
    db.commit()
    row = db.query(Order).filter_by(order_remark="10000001").first()
    assert row.order_id == "BROKER-OID-1"
    assert row.status == "49"
    db.close()


def test_ord_cfm_updates_traded_volume():
    """部成推送 → 更新 traded_volume/avg_price"""
    db = SessionLocal()
    db.add(Order(
        order_id="OID-PART", client_order_id="CID-PART", order_no="10000002",
        order_remark="10000002", TRD_DATE="20260614",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "OID-PART",
        "status": "50",  # 部成
        "traded_volume": 30,
        "traded_amount": 375.0,
        "avg_price": 12.5,
    }, ts="20260614 09:31:00")
    db.commit()
    row = db.query(Order).filter_by(order_id="OID-PART").first()
    assert row.status == "50"
    assert row.traded_volume == 30
    assert row.avg_price == 12.5
    db.close()


def test_ord_cfm_logs_warn_when_no_local_order(capfd):
    """push 来了但本地无对应 Order → 打 WARN 不创建"""
    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "GHOST-OID",
        "status": "49",
    }, ts="20260614 09:30:00")
    db.commit()
    # 不会有新行
    assert db.query(Order).count() == 0
    db.close()


# ──── trd_cfm ────

def test_trd_cfm_inserts_trade_and_updates_order():
    db = SessionLocal()
    db.add(Order(
        order_id="OID-T", client_order_id="CID-T", order_no="10000010",
        order_remark="10000010", TRD_DATE="20260614",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0, traded_amount=0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "trade_id": "TID-001",
        "order_id": "OID-T",
        "stock_code": "600030.SH",
        "order_type": "23",
        "price": 12.5,
        "volume": 30,
        "amount": 375.0,
        "trade_time": "09:31:00",
    }, ts="20260614 09:31:00")
    db.commit()

    t = db.query(Trade).filter_by(trade_id="TID-001").first()
    assert t is not None
    assert t.stock_code == "600030.SH"
    assert t.volume == 30
    assert t.price == 12.5
    assert t.TRD_DATE == "20260614"

    # Order 累计更新
    o = db.query(Order).filter_by(order_id="OID-T").first()
    assert o.traded_volume == 30
    assert o.traded_amount == 375.0
    assert o.avg_price == 12.5
    db.close()


def test_trd_cfm_idempotent():
    """同 trade_id 二次推送 → 不会重复插入"""
    db = SessionLocal()
    db.add(Order(
        order_id="OID-IDEM", client_order_id="CID-IDEM", order_no="10000020",
        order_remark="10000020", TRD_DATE="20260614",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    payload = {
        "trade_id": "TID-DUP",
        "order_id": "OID-IDEM",
        "stock_code": "600030.SH",
        "price": 12.5, "volume": 10, "amount": 125.0,
    }

    db = SessionLocal()
    handle_push(db, "trd_cfm", payload, ts="x")
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", payload, ts="x")
    db.commit()
    assert db.query(Trade).filter_by(trade_id="TID-DUP").count() == 1
    db.close()


# ──── pos_cfm ────

def test_pos_cfm_upserts_position():
    db = SessionLocal()
    # 第一次推送
    handle_push(db, "pos_cfm", {
        "stock_code": "600030.SH",
        "volume": 1000,
        "available": 1000,
        "cost_price": 12.5,
        "market_value": 12500.0,
    }, ts="20260614 09:30:00")
    db.commit()
    db.close()

    # 重新读
    db = SessionLocal()
    p = db.query(Position).filter_by(stock_code="600030.SH", TRD_DATE="20260614").first()
    assert p is not None
    assert p.total == 1000
    assert p.cost == 12.5
    db.close()

    # 第二次推送 → 覆盖
    db = SessionLocal()
    handle_push(db, "pos_cfm", {
        "stock_code": "600030.SH",
        "volume": 1100,
        "available": 1100,
        "cost_price": 12.45,
        "market_value": 13695.0,
    }, ts="20260614 14:00:00")
    db.commit()
    p = db.query(Position).filter_by(stock_code="600030.SH", TRD_DATE="20260614").first()
    assert p.total == 1100
    assert p.cost == 12.45
    db.close()


# ──── ast_cfm ────

def test_ast_cfm_upserts_asset():
    db = SessionLocal()
    handle_push(db, "ast_cfm", {
        "total_asset": 100000.0,
        "cash": 50000.0,
        "frozen": 1000.0,
        "market_value": 50000.0,
    }, ts="20260614 09:30:00")
    db.commit()
    a = db.query(Asset).filter_by(TRD_DATE="20260614").first()
    assert a is not None
    assert a.total_asset == 100000.0
    assert a.cash == 50000.0
    assert a.frozen_cash == 1000.0
    db.close()


def test_ast_cfm_overwrites_on_second_push():
    db = SessionLocal()
    handle_push(db, "ast_cfm", {
        "total_asset": 100000.0, "cash": 50000.0, "frozen": 0, "market_value": 50000.0,
    }, ts="x")
    db.commit()
    handle_push(db, "ast_cfm", {
        "total_asset": 150000.0, "cash": 100000.0, "frozen": 0, "market_value": 50000.0,
    }, ts="y")
    db.commit()
    a = db.query(Asset).filter_by(TRD_DATE="20260614").first()
    assert a.total_asset == 150000.0
    assert a.cash == 100000.0
    db.close()


# ──── 路由 ────

def test_unknown_func_skipped_silently():
    """未知 func 不报错"""
    db = SessionLocal()
    handle_push(db, "unknown_func", {"foo": "bar"}, ts="x")
    db.commit()  # 不报错即 OK
    db.close()
