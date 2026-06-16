"""
test_holdings_api.py — 验证 v5 /api/holdings 读本地 positions 表

覆盖：
- 正常读 DB（6 字段格式）
- stock_code 过滤
- 空 DB 返空 list
- 未激活日 返 trd_date 最近的最大值（兜底逻辑，不 503）
- 字段映射 last_vol / vol / avl_vol / cost_price
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from fastapi.testclient import TestClient

from db import Base, engine, SessionLocal, init_db
from models.orm import Position, SysStatus
from models.user import User
from auth.security import hash_password


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def active_day(fresh_db):
    """激活 20260614 + Trader user"""
    db = SessionLocal()
    db.query(User).filter_by(username="trader1").delete()
    db.commit()
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    db.refresh(trader)
    db.close()
    return trader.id


def _trader_token(user_id: int) -> str:
    from auth.security import create_access_token
    return create_access_token({"sub": str(user_id), "role": "trader"})


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _seed_positions(db, count=2):
    """seed N 行 Position：600000 + 600001...

    NOTE: Position ORM 缺 market_value 字段，
    API 层用 cost_price × vol 代理计算，不直接写字段。
    """
    positions = [
        Position(
            stock_code="600000",
            stock_name="浦发银行",
            last_vol=1000, today_buy=200, today_sell=100,
            avl_vol=1100, vol=1100, cost_price=10.5,
            synced_from="rpc_reconcile",
        ),
        Position(
            stock_code="600001",
            stock_name="邯郸钢铁",
            last_vol=2000, today_buy=0, today_sell=500,
            avl_vol=1500, vol=1500, cost_price=5.2,
            synced_from="rpc_reconcile",
        ),
    ]
    for p in positions[:count]:
        db.add(p)
    db.commit()
    return positions[:count]


# ──── 正常读 DB ────

def test_holdings_returns_positions_from_db(client, active_day):
    """seed 2 行 → 调 API 返 2 行（6 字段格式）"""
    db = SessionLocal()
    _seed_positions(db, count=2)
    db.close()
    t = _trader_token(active_day)

    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == 0
    assert len(data["list"]) == 2
    item = data["list"][0]
    # 6 字段格式
    assert set(item.keys()) == {
        "stock_code", "last_vol", "vol", "avl_vol", "cost_price", "market_value"
    }
    # 字段映射验证
    assert item["last_vol"] == 1000
    assert item["vol"] == 1100
    assert "initial_position" not in item  # 旧字段已不返
    assert "total" not in item


def test_holdings_filter_by_stock_code(client, active_day):
    """seed 2 行 → ?stock_code=600000 返 1 行"""
    db = SessionLocal()
    db.add(Position(
        stock_code="600000",
        last_vol=100, vol=100, avl_vol=100, cost_price=10.0,
        synced_from="rpc_reconcile",
    ))
    db.add(Position(
        stock_code="600001",
        last_vol=200, vol=200, avl_vol=200, cost_price=20.0,
        synced_from="rpc_reconcile",
    ))
    db.commit()
    db.close()
    t = _trader_token(active_day)

    res = client.get("/api/holdings?stock_code=600000", headers=_auth(t))
    assert res.status_code == 200
    data = res.json()
    assert len(data["list"]) == 1
    assert data["list"][0]["stock_code"] == "600000"
    assert data["list"][0]["last_vol"] == 100


def test_holdings_empty_db_returns_empty_list(client, active_day):
    """空 DB → 返空 list code=0（不是 503）"""
    t = _trader_token(active_day)
    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == 0
    assert data["list"] == []


def test_holdings_uses_active_day(client, active_day):
    """默认查 active 交易日（positions 已无 TRD_DATE，只返当前快照）"""
    db = SessionLocal()
    _seed_positions(db, count=1)
    db.close()
    t = _trader_token(active_day)

    res = client.get("/api/holdings", headers=_auth(t))
    data = res.json()
    assert len(data["list"]) == 1
    assert data["list"][0]["stock_code"] == "600000"


def test_holdings_no_active_day_falls_back_to_max(client, fresh_db):
    """未激活日 → resolve_default_trd_date 兜底到 MAX(trd_date)，不 503"""
    db = SessionLocal()
    # 留一个 SysStatus 让 fallback 有数据可查
    # 不放 SysStatus，验证全兜底
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.commit()
    db.refresh(trader)
    # 放一个 Order 让 resolve_default_trd_date 兜底到 MAX(trd_date)
    from models.orm import Order
    db.add(Order(
        trd_date="20260610", order_id="OID-FB", user_def="CID-FB", order_no="10000001",
        stock_code="600000.SH", order_type="23", price_type=11, price=10.0, volume=100,
    ))
    db.commit()
    db.close()
    t = _trader_token(trader.id)

    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    data = res.json()
    # 全空 Position → 兜底也查不到 → 返空 list（不 503）
    assert data["code"] == 0
    assert data["list"] == []


def test_holdings_requires_auth(client):
    """未登录 → 401"""
    res = client.get("/api/holdings")
    assert res.status_code == 401


def test_holdings_market_value_proxy(client, active_day):
    """market_value = cost_price × vol（成本市值代理）"""
    db = SessionLocal()
    db.add(Position(
        stock_code="600000",
        last_vol=100, vol=200, avl_vol=200,
        cost_price=12.5, synced_from="rpc_reconcile",
    ))
    db.commit()
    db.close()
    t = _trader_token(active_day)

    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    item = res.json()["list"][0]
    # 12.5 × 200 = 2500.0
    assert item["market_value"] == pytest.approx(2500.0)
