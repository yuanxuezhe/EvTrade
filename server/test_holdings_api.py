"""
test_holdings_api.py — 验证 v5 /api/holdings 读本地 positions 表（v4 漏改端点）

覆盖：
- 正常读 DB（6 字段格式）
- stock_code 过滤
- 空 DB 返空 list
- 未激活日 返 TRD_DATE 最近的最大值（兜底逻辑，不 503）
- 字段映射 initial_position / total
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from fastapi.testclient import TestClient

from db import Base, engine, SessionLocal, init_db
from models.orm import Position, TradingDay
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
    db.add(TradingDay(current_date="20260614", status="active"))
    db.commit()
    db.refresh(trader)
    db.close()
    return trader.id


def _trader_token(user_id: int) -> str:
    from auth.security import create_access_token
    return create_access_token({"sub": str(user_id), "role": "trader"})


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _seed_positions(db, trd_date="20260614", count=2):
    """seed 2 行 Position：600000 + 600001

    NOTE: Position ORM 缺 market_value 字段（v4 bug，2026-06-15 标记），
    API 层用 cost × total 代理计算，不直接写字段。
    """
    positions = [
        Position(
            TRD_DATE=trd_date,
            stock_code="600000",
            stock_name="浦发银行",
            initial_position=1000, today_buy=200, today_sell=100,
            available=1100, total=1100, cost=10.5,
            synced_from="rpc_reconcile",
        ),
        Position(
            TRD_DATE=trd_date,
            stock_code="600001",
            stock_name="邯郸钢铁",
            initial_position=2000, today_buy=0, today_sell=500,
            available=1500, total=1500, cost=5.2,
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
        "stock_code", "initial_position", "total", "available", "cost", "market_value"
    }
    # 字段映射验证
    assert item["initial_position"] == 1000
    assert item["total"] == 1100
    assert "last_vol" not in item  # 旧字段已不返
    assert "volume" not in item


def test_holdings_filter_by_stock_code(client, active_day):
    """seed 3 行 → ?stock_code=600000 返 1 行"""
    db = SessionLocal()
    db.add(Position(
        TRD_DATE="20260614", stock_code="600000",
        initial_position=100, total=100, available=100, cost=10.0,
        synced_from="rpc_reconcile",
    ))
    db.add(Position(
        TRD_DATE="20260614", stock_code="600001",
        initial_position=200, total=200, available=200, cost=20.0,
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
    assert data["list"][0]["initial_position"] == 100


def test_holdings_empty_db_returns_empty_list(client, active_day):
    """空 DB → 返空 list code=0（不是 503）"""
    t = _trader_token(active_day)
    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == 0
    assert data["list"] == []


def test_holdings_uses_active_day(client, active_day):
    """默认查 active 交易日"""
    db = SessionLocal()
    _seed_positions(db, trd_date="20260614", count=1)
    # 另一天数据不应被返
    db.add(Position(
        TRD_DATE="20260613", stock_code="000001",
        initial_position=999, total=999, available=999,
        cost=1.0, synced_from="rpc_reconcile",
    ))
    db.commit()
    db.close()
    t = _trader_token(active_day)

    res = client.get("/api/holdings", headers=_auth(t))
    data = res.json()
    assert len(data["list"]) == 1
    assert data["list"][0]["stock_code"] == "600000"


def test_holdings_no_active_day_falls_back_to_max(client, fresh_db):
    """未激活日 → resolve_default_trd_date 兜底到 MAX(TRD_DATE)，不 503"""
    db = SessionLocal()
    # 无 TradingDay，但有 positions 数据
    db.add(Position(
        TRD_DATE="20260610", stock_code="600000",
        initial_position=50, total=50, available=50,
        cost=10.0, synced_from="rpc_reconcile",
    ))
    db.commit()
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.commit()
    db.refresh(trader)
    db.close()
    t = _trader_token(trader.id)

    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    data = res.json()
    assert len(data["list"]) == 1
    # 兜底返回 MAX(TRD_DATE) 的数据；具体日期由 guards 决定，6 字段格式不返 TRD_DATE
    assert data["list"][0]["stock_code"] == "600000"


def test_holdings_requires_auth(client):
    """未登录 → 401"""
    res = client.get("/api/holdings")
    assert res.status_code == 401


def test_holdings_market_value_proxy(client, active_day):
    """market_value = cost × total（成本市值代理，待 v4 bug 修复后改回读字段）"""
    db = SessionLocal()
    db.add(Position(
        TRD_DATE="20260614", stock_code="600000",
        initial_position=100, total=200, available=200,
        cost=12.5, synced_from="rpc_reconcile",
    ))
    db.commit()
    db.close()
    t = _trader_token(active_day)

    res = client.get("/api/holdings", headers=_auth(t))
    assert res.status_code == 200
    item = res.json()["list"][0]
    # 12.5 × 200 = 2500.0
    assert item["market_value"] == pytest.approx(2500.0)
