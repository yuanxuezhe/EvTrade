"""
test_adjust.py — v12 PUT /api/asset/adjust 端点测试（admin 鉴权）

覆盖：
- 调增 cash 成功 → 响应 + DB 写入 + synced_from=manual
- 调减 cash 允许负值（broker 可透支场景）
- 缺字段（delta_cash / delta_total_asset 都不传） → 422
- 非 admin 返 403

fixtures 与 tests/server/api/orders/test_place.py 风格一致：
fresh_db / admin_token / admin_id / client
"""
import pytest
from datetime import time

from fastapi.testclient import TestClient

from server.db import Base, engine, SessionLocal, init_db
from server.models.orm import Asset, TradingSession, SysStatus
from server.models.user import User
from server.auth.security import hash_password, create_access_token


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    from server.main import app
    return TestClient(app)


@pytest.fixture
def admin_id(fresh_db):
    """admin user fixture（用于 issue admin token）"""
    db = SessionLocal()
    db.query(User).filter_by(username="admin1").delete()
    db.commit()
    user = User(username="admin1", password_hash=hash_password("x"), role="admin")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user.id


@pytest.fixture
def trader_id(fresh_db):
    """trader user fixture（用于负面测试：403 拒绝）"""
    db = SessionLocal()
    db.query(User).filter_by(username="trader1").delete()
    db.commit()
    user = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user.id


def _token(user_id: int, role: str) -> str:
    return create_access_token({"sub": str(user_id), "role": role})


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _seed_asset(cash: float = 5000.0, total_asset: float = 8000.0) -> None:
    """seed Asset 单行（生产场景：do_reconcile 已写入）"""
    db = SessionLocal()
    db.query(Asset).delete()
    db.add(Asset(
        cash=cash, frozen_cash=0.0, market_value=3000.0, total_asset=total_asset,
        synced_at=None, synced_from="rpc_full",
    ))
    db.commit()
    db.close()


# ──── 1. 调增 cash 成功 ────

def test_adjust_asset_increase_cash_success(client, admin_id):
    """调增 cash 1000 → DB cash=6000, synced_from=manual"""
    _seed_asset(cash=5000.0, total_asset=8000.0)

    r = client.put(
        "/api/asset/adjust",
        json={"delta_cash": 1000.0, "reason": "银证转账入金"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["asset"]["cash"] == 6000.0
    assert body["asset"]["synced_from"] == "manual"
    assert body["asset"]["synced_at"] is not None

    # verify DB
    db = SessionLocal()
    row = db.query(Asset).first()
    db.close()
    assert row.cash == 6000.0
    assert row.synced_from == "manual"


def test_adjust_asset_increase_total_asset_success(client, admin_id):
    """仅调增 total_asset（cash 不动）"""
    _seed_asset(cash=5000.0, total_asset=8000.0)

    r = client.put(
        "/api/asset/adjust",
        json={"delta_total_asset": 500.0, "reason": "基金市值修正"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset"]["cash"] == 5000.0          # cash 不变
    assert body["asset"]["total_asset"] == 8500.0  # total += 500


# ──── 2. 调减 cash 允许负值（broker 可透支） ────

def test_adjust_asset_negative_cash_allows_overdraft(client, admin_id):
    """delta_cash=-800, 原 cash=500 → 期望 cash=-300（broker 可透支场景）"""
    _seed_asset(cash=500.0, total_asset=8000.0)

    r = client.put(
        "/api/asset/adjust",
        json={"delta_cash": -800.0, "reason": "透支调平"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset"]["cash"] == -300.0  # 500 + (-800) = -300
    assert body["asset"]["synced_from"] == "manual"


# ──── 3. 缺字段返 422 ────

def test_adjust_asset_empty_body_returns_422(client, admin_id):
    """delta_cash + delta_total_asset 都缺（或都为 None） → 422"""
    _seed_asset(cash=5000.0, total_asset=8000.0)

    r = client.put(
        "/api/asset/adjust",
        json={},
        headers=_auth(_token(admin_id, "admin")),
    )
    # Pydantic 422 因为 `at least one` 校验失败
    assert r.status_code == 422, r.text


def test_adjust_asset_no_deltas_returns_422(client, admin_id):
    """显式传 None 不算 delta"""
    r = client.put(
        "/api/asset/adjust",
        json={"delta_cash": None, "delta_total_asset": None},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 422


def test_adjust_asset_only_reason_returns_422(client, admin_id):
    """只传 reason 不传任何 delta → 422"""
    r = client.put(
        "/api/asset/adjust",
        json={"reason": "no-op"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 422


# ──── 4. 非 admin 返 403 ────

def test_adjust_asset_trader_returns_403(client, trader_id):
    """trader 调 PUT /api/asset/adjust → 403"""
    _seed_asset(cash=5000.0)

    r = client.put(
        "/api/asset/adjust",
        json={"delta_cash": 1000.0},
        headers=_auth(_token(trader_id, "trader")),
    )
    assert r.status_code == 403, r.text


def test_adjust_asset_unauthenticated_returns_401(client):
    """无 token → 401"""
    r = client.put("/api/asset/adjust", json={"delta_cash": 100.0})
    assert r.status_code == 401
