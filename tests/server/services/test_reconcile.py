"""
test_reconcile.py — v5 重构版（schema refactor: trading_day→sys_status, 字段重命名）

v5 改动：
- URL /api/admin/trading-day → /api/admin/sys-status
- 请求体 / 响应字段 TRD_DATE → trd_date
- TradingDay → SysStatus; current_date → trd_date
- Position 字段重命名
- Asset 无 TRD_DATE 字段
- 不再调用 qry_orders / qry_trades（v7 简化: 委托/成交不走对账）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
import json
from datetime import datetime, time
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from db import Base, engine, init_db, SessionLocal
from models.orm import (
    Order, Trade, Position, Asset, SysStatus,
    ReconcileConfig, ReconcileReport,
)
from models.user import User
from auth.security import hash_password


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


def _admin_token():
    db = SessionLocal()
    admin = db.query(User).filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
        db.add(admin)
        db.commit()
        db.refresh(admin)
    db.close()
    from auth.security import create_access_token
    return create_access_token({"sub": str(admin.id), "role": "admin"})


def _auth(t): return {"Authorization": f"Bearer {t}"}


# ──── reconcile_config 读写 ────

def test_reconcile_config_get_default_creates():
    client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
    r = client.get("/api/admin/reconcile/config", headers=_auth(_admin_token()))
    assert r.status_code == 200
    assert r.json()["auto_reconcile"] is False


def test_reconcile_config_update():
    client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
    r = client.patch(
        "/api/admin/reconcile/config",
        json={"auto_reconcile": True},
        headers=_auth(_admin_token()),
    )
    assert r.status_code == 200
    assert r.json()["auto_reconcile"] is True
    r2 = client.get("/api/admin/reconcile/config", headers=_auth(_admin_token()))
    assert r2.json()["auto_reconcile"] is True


# ──── 日初：init ────

def test_init_trading_day_with_auto_reconcile():
    """auto_reconcile=True → 切交易日 + 覆盖本地"""
    db = SessionLocal()
    admin = User(username="admin", password_hash=hash_password("x"), role="admin")
    db.add(admin)
    cfg = ReconcileConfig(auto_reconcile=True, updated_by="admin")
    db.add(cfg)
    db.commit()
    db.close()

    # v7 简化: 委托/成交不再调 qry_orders / qry_trades
    # change consolidate-position-data-flow: mock 数据使用 parser 输出 dict 键名
    # (即与 Position ORM 列名一致: vol/avl_vol/cost_price, 不再有 volume/avl_amt/avg_price/market_value)
    # change add-manual-adjust-and-history-pages (v12): today_buy/today_sell 已删除
    mock_pos = AsyncMock(return_value={
        "code": 0, "msg": "ok", "list": [
            {"stock_code": "600030.SH", "vol": 100, "avl_vol": 100,
             "cost_price": 12.5,
             "last_vol": 0},
        ]
    })
    mock_asset = AsyncMock(return_value={
        "code": 0, "msg": "ok", "list": [
            {"account_id": "ACC-001",
             "total_asset": 101250.0, "cash": 100000.0, "frozen_cash": 0,
             "market_value": 1250.0},
        ]
    })

    with patch("services.reconcile.qry_positions", mock_pos), \
         patch("services.reconcile.qry_asset", mock_asset):

        client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
        r = client.post(
            "/api/admin/sys-status/init",
            json={"trd_date": "20260614"},
            headers=_auth(_admin_token()),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["applied"] is True
        assert body["trading_day"]["trd_date"] == "20260614"
        assert body["trading_day"]["status"] == "active"

        # 验证：本地 Position 表有 1 行（按 stock_code PK 查）
        db = SessionLocal()
        assert db.query(Position).filter_by(stock_code="600030.SH").count() == 1
        # Asset 单行
        assert db.query(Asset).count() == 1
        # SysStatus 切到了 20260614
        active = db.query(SysStatus).filter_by(status="active").first()
        assert active.trd_date == "20260614"
        # 对账报告生成
        assert db.query(ReconcileReport).count() == 1
        db.close()


def test_init_trading_day_rpc_fail_does_not_switch_day():
    """RPC 全失败 → 切不交易日 + 返错误"""
    db = SessionLocal()
    admin = User(username="admin", password_hash=hash_password("x"), role="admin")
    db.add(admin)
    cfg = ReconcileConfig(auto_reconcile=True, updated_by="admin")
    db.add(cfg)
    db.commit()
    db.close()

    fail_rpc = AsyncMock(side_effect=Exception("rpc 断连"))

    with patch("services.reconcile.qry_positions", fail_rpc), \
         patch("services.reconcile.qry_asset", fail_rpc):

        client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
        r = client.post(
            "/api/admin/sys-status/init",
            json={"trd_date": "20260614"},
            headers=_auth(_admin_token()),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 1  # 失败
        assert "rpc" in body["error"].lower() or "断连" in body["error"]
        assert body["trading_day"] is None

        # 关键：SysStatus 没切
        db = SessionLocal()
        active = db.query(SysStatus).filter_by(status="active").first()
        assert active is None
        # 对账报告写了
        assert db.query(ReconcileReport).count() == 1
        db.close()


def test_init_trading_day_manual_mode_writes_report_no_apply():
    """auto_reconcile=False → 只写报告不动数据 + 仍切交易日"""
    db = SessionLocal()
    admin = User(username="admin", password_hash=hash_password("x"), role="admin")
    db.add(admin)
    cfg = ReconcileConfig(auto_reconcile=False, updated_by="admin")
    db.add(cfg)
    db.commit()
    db.close()

    with patch("services.reconcile.qry_positions",
               AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})), \
         patch("services.reconcile.qry_asset",
               AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})):

        client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
        r = client.post(
            "/api/admin/sys-status/init",
            json={"trd_date": "20260614"},
            headers=_auth(_admin_token()),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["applied"] is False
        # 交易日切了
        assert body["trading_day"]["trd_date"] == "20260614"
        # 报告写了
        db = SessionLocal()
        assert db.query(ReconcileReport).count() == 1
        # 本地 Position 表没有（没覆盖）
        assert db.query(Position).count() == 0
        db.close()


def test_init_invalid_trd_date_returns_400():
    db = SessionLocal()
    db.add(User(username="admin", password_hash=hash_password("x"), role="admin"))
    db.commit()
    db.close()

    client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
    r = client.post(
        "/api/admin/sys-status/init",
        json={"trd_date": "bad"},
        headers=_auth(_admin_token()),
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_TRD_DATE"


def test_init_requires_admin():
    """非 admin 角色 → 403"""
    db = SessionLocal()
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.commit()
    db.close()
    from auth.security import create_access_token
    tok = create_access_token({"sub": "1", "role": "trader"})

    client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
    r = client.post(
        "/api/admin/sys-status/init",
        json={"trd_date": "20260614"},
        headers=_auth(tok),
    )
    assert r.status_code == 403


# ──── reports 列表 ────

def test_list_reports():
    """GET /api/admin/reconcile/reports 列出报告"""
    db = SessionLocal()
    admin = User(username="admin", password_hash=hash_password("x"), role="admin")
    db.add(admin)
    for i in range(3):
        db.add(ReconcileReport(
            trd_date=f"2026061{i+1}", diffs_json="{}", mode="manual",
            rpc_status="ok", error_message="",
        ))
    db.commit()
    db.close()

    client = TestClient(__import__("main", fromlist=["app"]).__getattribute__("app"))
    r = client.get("/api/admin/reconcile/reports", headers=_auth(_admin_token()))
    assert r.status_code == 200
    assert len(r.json()) == 3
