"""
test_api.py — strategy REST API 单测（task 9）

覆盖（14 用例）：
- 灰度：STRATEGY_ENGINE_ENABLED=false → 503
- CRUD：list / create / detail / update / delete
- 嵌套：regimes.grids 一并创建 + cascade 删除
- 鉴权：trader 只能管自己的；admin 可管全部
- 控制：pause / resume / stop 状态切换；clear_now 写 audit
- audit 查询：trd_date 过滤
- flags/definitions：9 条注册
"""
import sys
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from dataclasses import replace

from server.db import Base, engine, init_db, SessionLocal
from server.config import settings
from server.models.orm import Order, Trade
from server.models.user import User
from server.auth.security import hash_password, create_access_token
from server.services.strategy import repository as strat_repo


# ─────────────── Fixtures ───────────────


class _FakeQuoteConsumer:
    """测试用 fake — 避免真实 WS 连接尝试"""
    def subscribe_strategy(self, strategy_id, stock_code):
        pass
    def unsubscribe_strategy(self, strategy_id):
        pass


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    SessionLocal().close()


@pytest.fixture
def enable_engine(monkeypatch):
    """STRATEGY_ENGINE_ENABLED=True + fake quote_consumer（避开真实 WS 连接）"""
    import server.api.strategy.endpoints as ep_mod
    monkeypatch.setattr(ep_mod, "settings", replace(settings, STRATEGY_ENGINE_ENABLED=True))
    fake = _FakeQuoteConsumer()
    async def fake_get():
        return fake
    monkeypatch.setattr("server.services.strategy.quote_consumer.get_quote_consumer", fake_get)
    monkeypatch.setattr("server.services.strategy.quote_consumer._quote_consumer", fake)


@pytest.fixture
def disable_engine(monkeypatch):
    """STRATEGY_ENGINE_ENABLED=False"""
    import server.api.strategy.endpoints as ep_mod
    monkeypatch.setattr(ep_mod, "settings", replace(settings, STRATEGY_ENGINE_ENABLED=False))


@pytest.fixture
def client():
    from server.main import app
    return TestClient(app)


def _mk_user(username, role="trader"):
    db = SessionLocal()
    db.query(User).filter_by(username=username).delete()
    u = User(username=username, password_hash=hash_password("x"), role=role)
    db.add(u)
    db.commit()
    db.refresh(u)
    db.close()
    return u.id, create_access_token({"sub": str(u.id), "role": role})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def trader():
    uid, token = _mk_user("t_api_trader", "trader")
    return {"id": uid, "token": token}


@pytest.fixture
def admin():
    uid, token = _mk_user("t_api_admin", "admin")
    return {"id": uid, "token": token}


@pytest.fixture
def other_trader():
    uid, token = _mk_user("t_api_other", "trader")
    return {"id": uid, "token": token}


def _payload(stock_code="600519.SH", type_="general", n_regimes=1, n_grids=2):
    """合法 create payload：1 regime + N grids"""
    regs = []
    for i in range(n_regimes):
        regs.append({
            "name": f"R{i+1}",
            "priority": 10 * (i + 1),
            "required_flags": ["ma_bullish"],
            "exclude_flags": [],
            "grids": [
                {
                    "direction": "buy" if j % 2 == 0 else "sell",
                    "trigger_price": 10.0 + j,
                    "volume": 100,
                    "priority": j,
                } for j in range(n_grids)
            ],
        })
    return {
        "stock_code": stock_code, "type": type_,
        "reference_price": 10.0, "base_volume": 100, "note": "test",
        "regimes": regs,
    }


# ─────────────── 灰度门 ───────────────


def test_engine_disabled_returns_503(client, trader, disable_engine):
    """STRATEGY_ENGINE_ENABLED=false → 503 STRATEGY_ENGINE_DISABLED"""
    res = client.get("/api/strategy", headers=_auth(trader["token"]))
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "STRATEGY_ENGINE_DISABLED"


# ─────────────── CRUD ───────────────


def test_list_strategies_filters_by_user(client, trader, other_trader, enable_engine):
    """trader A 看不到 trader B 的策略"""
    # trader 创建 1 个，其他 trader 创建 1 个
    client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"]))
    client.post("/api/strategy", json=_payload("000001.SZ"), headers=_auth(other_trader["token"]))

    res = client.get("/api/strategy", headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["stock_code"] == "600519.SH"


def test_create_strategy_with_nested(client, trader, enable_engine):
    """POST / 创建策略 + 嵌套 regimes + grids（事务）"""
    res = client.post("/api/strategy", json=_payload(n_regimes=2, n_grids=2), headers=_auth(trader["token"]))
    assert res.status_code == 201
    data = res.json()
    assert data["stock_code"] == "600519.SH"
    assert data["status"] == "active"
    assert data["user_id"] == trader["id"]
    assert len(data["regimes"]) == 2
    assert all(len(r["grids"]) == 2 for r in data["regimes"])
    # flags / required_flags 序列化正确
    assert data["regimes"][0]["required_flags"] == ["ma_bullish"]


def test_get_detail_eager_loads_regimes_grids(client, trader, enable_engine):
    """GET /{id} 返 detail 含 regimes.grids"""
    create_res = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"]))
    sid = create_res.json()["id"]
    res = client.get(f"/api/strategy/{sid}", headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == sid
    assert len(data["regimes"]) == 1
    assert len(data["regimes"][0]["grids"]) == 2


def test_update_strategy_status(client, trader, enable_engine):
    """PUT / 改 status / base_volume"""
    create_res = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"]))
    sid = create_res.json()["id"]
    res = client.put(f"/api/strategy/{sid}", json={"status": "paused", "base_volume": 200},
                     headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "paused"
    assert data["base_volume"] == 200


def test_delete_strategy_cascades(client, trader, enable_engine):
    """DELETE / 级联删 regimes + grids + audits"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    # 加 audit 一行
    db = SessionLocal()
    strat_repo.write_audit(db, strategy_id=sid, trd_date="20260706", trigger_type="test_audit")
    db.commit()
    db.close()
    # delete
    res = client.delete(f"/api/strategy/{sid}", headers=_auth(trader["token"]))
    assert res.status_code == 204
    # verify cascade
    db = SessionLocal()
    from sqlalchemy import text
    counts = {
        "strategy": db.execute(text("SELECT COUNT(*) FROM strategy WHERE id=:id"), {"id": sid}).scalar(),
        "regime": db.execute(text("SELECT COUNT(*) FROM strategy_regime WHERE strategy_id=:id"), {"id": sid}).scalar(),
        "grid": db.execute(text("SELECT COUNT(*) FROM strategy_grid WHERE regime_id IN (SELECT id FROM strategy_regime WHERE strategy_id=:id)"), {"id": sid}).scalar(),
        "audit": db.execute(text("SELECT COUNT(*) FROM strategy_audit WHERE strategy_id=:id"), {"id": sid}).scalar(),
    }
    db.close()
    assert counts == {"strategy": 0, "regime": 0, "grid": 0, "audit": 0}


# ─────────────── 鉴权 ───────────────


def test_other_trader_cannot_access_my_strategy(client, trader, other_trader, enable_engine):
    """trader B 访问 trader A 的策略 → 403"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    res = client.get(f"/api/strategy/{sid}", headers=_auth(other_trader["token"]))
    assert res.status_code == 403


def test_admin_can_access_any_strategy(client, trader, admin, enable_engine):
    """admin 可访问任意策略"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    res = client.get(f"/api/strategy/{sid}", headers=_auth(admin["token"]))
    assert res.status_code == 200


# ─────────────── 控制 ───────────────


def test_control_pause_resume_stop_changes_status(client, trader, enable_engine):
    """POST /{id}/control → status 切换 + audit"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    for action, expected_status in [("pause", "paused"), ("resume", "active"), ("stop", "stopped")]:
        res = client.post(f"/api/strategy/{sid}/control", json={"action": action}, headers=_auth(trader["token"]))
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == action
        assert data["status"] == expected_status
    # 3 个 audit 都写入
    db = SessionLocal()
    audits = db.query(__import__("server.services.strategy.models", fromlist=["StrategyAudit"]).StrategyAudit).filter_by(strategy_id=sid).all()
    db.close()
    trigger_types = {a.trigger_type for a in audits}
    assert {"control_pause", "control_resume", "control_stop"}.issubset(trigger_types)


def test_control_clear_now_writes_audit(client, trader, enable_engine):
    """clear_now 不改 status，但写 audit 标记意图"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    res = client.post(f"/api/strategy/{sid}/control", json={"action": "clear_now"}, headers=_auth(trader["token"]))
    assert res.status_code == 200
    # 查 audit
    db = SessionLocal()
    from server.services.strategy.models import StrategyAudit
    a = db.query(StrategyAudit).filter_by(strategy_id=sid, trigger_type="control_clear_now").first()
    db.close()
    assert a is not None
    assert a.get_action_payload() == {"action": "clear_now", "user_id": trader["id"]}


def test_control_invalid_action_returns_400(client, trader, enable_engine):
    """未知 action → 400 INVALID_ACTION"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    res = client.post(f"/api/strategy/{sid}/control", json={"action": "nuke"}, headers=_auth(trader["token"]))
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ACTION"


# ─────────────── Audit 查询 ───────────────


def test_audit_query_by_trd_date(client, trader, enable_engine):
    """GET /{id}/audit?trd_date=xxx → 当日 audit 列表倒序"""
    sid = client.post("/api/strategy", json=_payload(), headers=_auth(trader["token"])).json()["id"]
    db = SessionLocal()
    strat_repo.write_audit(db, strategy_id=sid, trd_date="20260706", trigger_type="a1")
    strat_repo.write_audit(db, strategy_id=sid, trd_date="20260706", trigger_type="a2")
    strat_repo.write_audit(db, strategy_id=sid, trd_date="20260705", trigger_type="a3")  # 前一天
    db.commit()
    db.close()

    res = client.get(f"/api/strategy/{sid}/audit?trd_date=20260706", headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    types = {a["trigger_type"] for a in data}
    assert types == {"a1", "a2"}


# ─────────────── Flags 注册表 ───────────────


def test_flags_definitions_returns_nine_flags(client, trader, enable_engine):
    """GET /flags/definitions → 9 条 flag 注册表"""
    res = client.get("/api/strategy/flags/definitions", headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()["list"]
    # flag_definitions() 返 9 条（spec REQ-STRAT-002）
    assert len(data) == 9
    codes = {d["code"] for d in data}
    assert "ma_bullish" in codes
    assert "macd_golden_cross" in codes


def test_flags_definitions_works_when_engine_disabled(client, trader, disable_engine):
    """/flags/definitions 是静态注册表，不受灰度门控制"""
    res = client.get("/api/strategy/flags/definitions", headers=_auth(trader["token"]))
    assert res.status_code == 200  # 200 不 503


# ─────────────── 鉴权（stranger）───────────────


def test_unauthenticated_returns_401(client, enable_engine):
    """无 token → 401"""
    res = client.get("/api/strategy")
    assert res.status_code == 401