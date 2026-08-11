"""
test_strategy_order_api.py — 母单 REST 端点测试 (v126, C4)

覆盖:
- 6 端点 + 错误码映射: NO_STRATEGY 404 / FORBIDDEN 403 / NO_BEST_PARAMS 400 / INVALID_STATE 409
- start 转发 strategy_exec (monkeypatch _forward_run_task 记录 payload)
- stop 转发 /internal/stop-task (monkeypatch httpx.AsyncClient.post)
- list/get/children 端到端
- 未认证 → 401

strategy_exec 转发全部 monkeypatch, 不连真实 8001。
"""
import os
import sys
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from fastapi.testclient import TestClient  # noqa: E402

from db import SessionLocal  # noqa: E402
from models.user import User  # noqa: E402
from auth.security import hash_password, create_access_token  # noqa: E402
from auth import session as auth_session  # noqa: E402
from server.main import app  # noqa: E402
from server.tables import Strategy, StrategyOrder, StrategyScript, StrategyTask  # noqa: E402
from server.services.script_strategy._convert import json_dumps  # noqa: E402

UID = 990010005
USERNAME = f"ut_order_api_{UID}"

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
    {"key": "slow", "type": "int", "min": 1, "max": 3, "step": 1, "default": 2},
]


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _cleanup():
    """按 username 拿真实 user_id 删 strategy/strategy_order/strategy_task/script/user."""
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=USERNAME).first()
        uid = u.id if u else None
    finally:
        db.close()
    if uid is not None:
        for so in StrategyOrder.query_by_fields({"user_id": uid}):
            StrategyOrder.delete_one(id=so._data["id"])
        for s in Strategy.query_by_fields({"user_id": uid}):
            sid = s._data.get("strategy_id")
            for t in StrategyTask.query_by_fields({"strategy_id": sid}):
                StrategyTask.delete_one(id=t._data["id"])
            Strategy.delete_one(strategy_id=sid)
        for sc in StrategyScript.query_by_fields({"user_id": uid}):
            StrategyScript.delete_one(user_id=uid, id=sc._data["id"])
    db = SessionLocal()
    try:
        db.query(User).filter_by(username=USERNAME).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def user_and_cleanup():
    _cleanup()
    db = SessionLocal()
    try:
        u = User(username=USERNAME, password_hash=hash_password("x"), role="trader")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    finally:
        db.close()
    token = create_access_token({"sub": str(uid), "role": "trader"})
    auth_session.register_token(token, uid, "trader")
    auth = {"Authorization": f"Bearer {token}"}
    yield auth
    _cleanup()


def _set_best(strategy_id: int) -> None:
    Strategy.update_one(
        {"best_params": json_dumps({"fast": 3, "slow": 2})},
        strategy_id=strategy_id,
    )


@pytest.fixture
def strategy_id(client, user_and_cleanup):
    script_id = f"ut_order_api_{UID}"
    r = client.post("/api/script-strategy/scripts", json={
        "name": script_id, "code": "def init(self): pass", "params_schema": SCHEMA,
    }, headers=user_and_cleanup)
    assert r.status_code == 201, r.text
    r2 = client.post("/api/script-strategy/strategies", json={
        "name": f"ut策略-{script_id}", "script_id": script_id, "stock_code": "600519.SH",
    }, headers=user_and_cleanup)
    assert r2.status_code == 201, r2.text
    _set_best(r2.json()["strategy_id"])
    return r2.json()["strategy_id"]


# ─────────────── 401 ───────────────

def test_unauthorized_401(client):
    assert client.get("/api/script-strategy/strategy-orders").status_code == 401
    assert client.post("/api/script-strategy/strategy-orders", json={"strategy_id": 1}).status_code == 401


# ─────────────── POST /strategy-orders ───────────────

def test_create_endpoint_happy(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    r = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["strategy_id"] == strategy_id
    assert body["user_id"] > 0
    assert body["status"] == "stopped"
    assert body["task_id"] > 0


def test_create_endpoint_no_best_params_400(client, user_and_cleanup, strategy_id):
    """清掉 best_params → 400 NO_BEST_PARAMS."""
    h = user_and_cleanup
    Strategy.update_one({"best_params": None}, strategy_id=strategy_id)
    r = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_BEST_PARAMS"


def test_create_endpoint_no_strategy_404(client, user_and_cleanup):
    h = user_and_cleanup
    r = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": 99999999}, headers=h)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NO_STRATEGY"


# ─────────────── GET /strategy-orders ───────────────

def test_list_endpoint(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h)
    r = client.get("/api/script-strategy/strategy-orders", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert any(d["strategy_id"] == strategy_id for d in r.json())


def test_get_endpoint(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]
    r = client.get(f"/api/script-strategy/strategy-orders/{rid}", headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == rid


def test_get_endpoint_not_found_404(client, user_and_cleanup):
    r = client.get("/api/script-strategy/strategy-orders/99999999", headers=user_and_cleanup)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "STRATEGY_ORDER_NOT_FOUND"


def test_children_endpoint(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]
    r = client.get(f"/api/script-strategy/strategy-orders/{rid}/children", headers=h)
    assert r.status_code == 200
    assert r.json() == []


# ─────────────── POST /start /stop /close ───────────────

def test_start_endpoint_forwards_run_task(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]

    calls: List[Dict[str, Any]] = []

    async def fake_forward(task_id, payload):
        calls.append({"task_id": task_id, "payload": payload})

    monkeypatch.setattr(
        "server.api.script_strategy.strategy_orders._forward_run_task", fake_forward,
    )

    r = client.post(f"/api/script-strategy/strategy-orders/{rid}/start", headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["active_task_id"] is not None
    assert body["forward_payload"]["parent_task_id"] == body["task_id"]
    assert body["forward_payload"]["mode"] == "live"
    assert body["forward_payload"]["strategy_name"]

    # 转发被调
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["strategy_id"] == strategy_id
    assert payload["mode"] == "live"
    assert payload["parent_task_id"] == body["task_id"]


def test_start_endpoint_no_best_params_400(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]
    # 母单建好后清掉 best_params → start 应 400 NO_BEST_PARAMS
    Strategy.update_one({"best_params": None}, strategy_id=strategy_id)
    r = client.post(f"/api/script-strategy/strategy-orders/{rid}/start", headers=h)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_BEST_PARAMS"


def test_start_endpoint_invalid_state_409(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]

    async def fake_forward(task_id, payload):
        pass
    monkeypatch.setattr(
        "server.api.script_strategy.strategy_orders._forward_run_task", fake_forward,
    )

    client.post(f"/api/script-strategy/strategy-orders/{rid}/start", headers=h)
    r = client.post(f"/api/script-strategy/strategy-orders/{rid}/start", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STRATEGY_ORDER_INVALID_STATE"


def test_stop_endpoint_forwards_stop_task(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]

    async def fake_forward(task_id, payload):
        pass
    monkeypatch.setattr(
        "server.api.script_strategy.strategy_orders._forward_run_task", fake_forward,
    )
    client.post(f"/api/script-strategy/strategy-orders/{rid}/start", headers=h)

    stop_calls: List[Dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, json=None, headers=None):
            stop_calls.append({"url": url, "json": json, "headers": headers})
            class R:
                status_code = 200
                text = "ok"
            return R()

    import server.api.script_strategy.strategy_orders as api_mod
    monkeypatch.setattr(api_mod.httpx, "AsyncClient", FakeAsyncClient)

    r = client.post(f"/api/script-strategy/strategy-orders/{rid}/stop", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "stopped"
    assert body["active_task_id"] is not None  # 转 stop 时返回原 active
    assert stop_calls, "stop-task 应该被转发"
    assert stop_calls[0]["json"]["task_id"] == body["active_task_id"]


def test_close_endpoint_happy(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]
    r = client.post(f"/api/script-strategy/strategy-orders/{rid}/close", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "closed"


def test_close_endpoint_running_409(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    rid = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h).json()["id"]

    async def fake_forward(task_id, payload):
        pass
    monkeypatch.setattr(
        "server.api.script_strategy.strategy_orders._forward_run_task", fake_forward,
    )
    client.post(f"/api/script-strategy/strategy-orders/{rid}/start", headers=h)
    r = client.post(f"/api/script-strategy/strategy-orders/{rid}/close", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STRATEGY_ORDER_INVALID_STATE"


def test_cross_user_forbidden_403(client, user_and_cleanup, strategy_id):
    """他人公开策略不可建母单 (FORBIDDEN 403)."""
    from db import SessionLocal
    db = SessionLocal()
    try:
        u2 = User(username=f"{USERNAME}_other", password_hash=hash_password("x"), role="trader")
        db.add(u2)
        db.commit()
        db.refresh(u2)
        other_uid = u2.id
    finally:
        db.close()
    token2 = create_access_token({"sub": str(other_uid), "role": "trader"})
    auth_session.register_token(token2, other_uid, "trader")
    h2 = {"Authorization": f"Bearer {token2}"}

    # 改 owner + 公开
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=USERNAME).first()
        real_uid = u.id
    finally:
        db.close()
    Strategy.update_one(
        {"is_public": 1, "user_id": real_uid},
        strategy_id=strategy_id,
    )
    r = client.post("/api/script-strategy/strategy-orders", json={"strategy_id": strategy_id}, headers=h2)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN"

    # 还原 + 清理
    Strategy.update_one(
        {"is_public": 0, "user_id": other_uid},  # 临时给 other_uid, 避免 owner 错位
        strategy_id=strategy_id,
    )
    db = SessionLocal()
    try:
        db.query(User).filter_by(username=f"{USERNAME}_other").delete()
        db.commit()
    finally:
        db.close()
