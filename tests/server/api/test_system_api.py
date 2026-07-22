"""
test_system_api.py — v8 新增

GET /api/system/active-day 测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from db import Base, engine, init_db, SessionLocal
from models.orm import SysStatus, TradingSession
from models.user import User
from auth.security import hash_password, create_access_token
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=__import__('datetime').time(9, 15),
        morning_end=__import__('datetime').time(11, 30),
        afternoon_start=__import__('datetime').time(13, 0),
        afternoon_end=__import__('datetime').time(15, 0),
    ))
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def trader_user(fresh_db):
    db = SessionLocal()
    u = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.close()
    return u


def _auth(u):
    token = create_access_token({"sub": str(u.id), "role": u.role})
    return {"Authorization": f"Bearer {token}"}


# ──── 正常情况：激活日存在 ────

def test_active_day_returns_rpc_format_with_trd_date(client, trader_user):
    """激活日存在 → 返标准 RPC {code:0, msg:"", list:[{trd_date, status}]}"""
    db = SessionLocal()
    db.add(SysStatus(id=1, trd_date="20260614", status="active"))
    db.commit()
    db.close()

    r = client.get("/api/system/active-day", headers=_auth(trader_user))
    assert r.status_code == 200
    body = r.json()
    # 必须是标准 RPC 格式
    assert body["code"] == 0
    assert "msg" in body
    assert "list" in body
    assert len(body["list"]) == 1
    assert body["list"][0]["trd_date"] == "20260614"
    assert body["list"][0]["status"] == "active"


# ──── 未激活：返空 list，code=0 ────

def test_active_day_no_active_returns_empty_list(client, trader_user):
    """没激活交易日 → 返 {code:0, list:[]}（不是错误，是未初始化状态）"""
    r = client.get("/api/system/active-day", headers=_auth(trader_user))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["list"] == []


# ──── pending 状态不算激活 ────

def test_active_day_pending_status_ignored(client, trader_user):
    """pending 状态不算激活（要 status='active'）"""
    db = SessionLocal()
    db.add(SysStatus(id=1, trd_date="20260615", status="pending"))
    db.commit()
    db.close()

    r = client.get("/api/system/active-day", headers=_auth(trader_user))
    assert r.status_code == 200
    assert r.json()["list"] == []


# ──── 单行单 active 记录：单行接口 ────

def test_active_day_single_row(client, trader_user):
    """v_next: sys_status 单行宽表 (id=1), 只 1 条 active, /active 端点直接返回"""
    db = SessionLocal()
    db.query(SysStatus).delete()
    db.add(SysStatus(id=1, trd_date="20260614", status="active"))
    db.commit()
    db.close()

    r = client.get("/api/admin/sys-status/active", headers=_auth(trader_user))
    body = r.json()
    assert body["trd_date"] == "20260614"
    assert body["status"] == "active"


# ──── 鉴权：未登录 401 ────

def test_active_day_requires_auth(client, fresh_db):
    """无 token → 401"""
    r = client.get("/api/system/active-day")
    assert r.status_code == 401
