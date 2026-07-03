"""
test_adjust.py — v12 PUT /api/positions/{stock_code}/adjust 端点测试（admin 鉴权）

覆盖：
- 调增 vol 成功 → 响应 + DB 写入 + synced_from=manual
- 不存在的 stock_code → 404
- trader（非 admin）返 403
- 只传 delta_vol → avl_vol 不动
- 同时传 delta_vol + delta_avl_vol → 两个都动
- 空 body → 422

fixtures 与 tests/server/api/asset/test_adjust.py 风格一致。
"""
import pytest
from datetime import time

from fastapi.testclient import TestClient

from server.db import Base, engine, SessionLocal, init_db
from server.models.orm import Position, TradingSession
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


def _seed_position(
    stock_code: str = "600030.SH",
    vol: int = 100,
    avl_vol: int = 100,
    cost_price: float = 12.5,
) -> None:
    """seed Position 单行（生产场景：do_reconcile 已写入）"""
    db = SessionLocal()
    db.query(Position).delete()
    db.add(Position(
        stock_code=stock_code,
        stock_name="中信证券",
        last_vol=100,
        avl_vol=avl_vol,
        vol=vol,
        cost_price=cost_price,
        synced_at=None,
        synced_from="rpc_full",
    ))
    db.commit()
    db.close()


# ──── 1. 调增 vol 成功 ────

def test_adjust_position_increase_vol_success(client, admin_id):
    """调增 vol 100（期权行权场景） → vol=200"""
    _seed_position(vol=100, avl_vol=100)

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 100, "reason": "期权行权"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    assert body["msg"] == "ok"
    assert body["position"]["vol"] == 200
    assert body["position"]["avl_vol"] == 100          # avl_vol 不传 → 不动
    assert body["position"]["synced_from"] == "manual"
    assert body["position"]["synced_at"] is not None
    assert body["position"]["stock_code"] == "600030.SH"

    # verify DB
    db = SessionLocal()
    row = db.query(Position).filter_by(stock_code="600030.SH").first()
    db.close()
    assert row.vol == 200
    assert row.avl_vol == 100
    assert row.synced_from == "manual"
    # cost_price / last_vol 不动（仅 do_reconcile 写）
    assert row.cost_price == 12.5
    assert row.last_vol == 100


def test_adjust_position_increase_both_vol_and_avl_vol(client, admin_id):
    """同时传 delta_vol + delta_avl_vol → 两个都动"""
    _seed_position(vol=100, avl_vol=100)

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 50, "delta_avl_vol": 30, "reason": "申赎到账"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["position"]["vol"] == 150
    assert body["position"]["avl_vol"] == 130


# ──── 2. 不存在的 stock_code → 404 ────

def test_adjust_position_unknown_stock_code_returns_404(client, admin_id):
    """不存在的 stock_code → 404 + 不自动新建"""
    _seed_position(stock_code="600030.SH")  # 存在的是 600030.SH，不是 UNKNOWN

    r = client.put(
        "/api/positions/UNKNOWN/adjust",
        json={"delta_vol": 100},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 404, r.text
    # 错误 detail 含 POSITION_NOT_FOUND 码（供前端过滤）
    assert "POSITION_NOT_FOUND" in str(r.json().get("detail", ""))

    # 确认未自动新建
    db = SessionLocal()
    row = db.query(Position).filter_by(stock_code="UNKNOWN").first()
    db.close()
    assert row is None, "未知 stock_code 不应自动创建 Position 行"


# ──── 3. trader → 403 ────

def test_adjust_position_trader_returns_403(client, trader_id):
    """trader 调调平端点 → 403"""
    _seed_position()

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 100},
        headers=_auth(_token(trader_id, "trader")),
    )
    assert r.status_code == 403


def test_adjust_position_unauthenticated_returns_401(client):
    """无 token → 401"""
    _seed_position()
    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 100},
    )
    assert r.status_code == 401


# ──── 4. 只传 delta_vol → avl_vol 不动 ────

def test_adjust_position_only_delta_vol_does_not_touch_avl(client, admin_id):
    """只传 delta_vol，未传 delta_avl_vol → avl_vol 保持原值"""
    _seed_position(vol=100, avl_vol=80)

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 50},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200
    assert r.json()["position"]["vol"] == 150
    assert r.json()["position"]["avl_vol"] == 80  # 不动


def test_adjust_position_only_delta_avl_vol_does_not_touch_vol(client, admin_id):
    """只传 delta_avl_vol，未传 delta_vol → vol 保持原值"""
    _seed_position(vol=100, avl_vol=80)

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_avl_vol": 20},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200
    assert r.json()["position"]["vol"] == 100  # 不动
    assert r.json()["position"]["avl_vol"] == 100


# ──── 5. synced_from 标记 manual ────

def test_adjust_position_marks_synced_from_manual(client, admin_id):
    """调平后 synced_from='manual'（再次 do_reconcile 会重置为 rpc_full）"""
    _seed_position()

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 10},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["position"]["synced_from"] == "manual"

    # 验证下一次调平会继续累加（manual 标记保持）
    r2 = client.put(
        "/api/positions/600030.SH/adjust",
        json={"delta_vol": 5},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r2.status_code == 200
    assert r2.json()["position"]["vol"] == 100 + 10 + 5
    assert r2.json()["position"]["synced_from"] == "manual"


# ──── 6. 空 body / 缺字段 → 422 ────

def test_adjust_position_empty_body_returns_422(client, admin_id):
    """delta_vol + delta_avl_vol 都不传 → 422"""
    _seed_position()

    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 422


def test_adjust_position_only_reason_returns_422(client, admin_id):
    """只传 reason → 422"""
    _seed_position()
    r = client.put(
        "/api/positions/600030.SH/adjust",
        json={"reason": "no-op"},
        headers=_auth(_token(admin_id, "admin")),
    )
    assert r.status_code == 422
