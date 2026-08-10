"""
test_strategy_v123_api.py — 策略/批次/实盘 API 端点测试 (v123 change task 6.2)

覆盖 (endpoint 层 + 转发 wiring):
- POST /strategies 建策略 → 201; GET list/detail → 200 (含脚本)
- POST /strategies/{id}/backtest:
    single → 202 + batch_no/total_runs=1; 转发 strategy_exec payload (task_id/strategy_id/mode=backtest)
    sweep  → 202 + total_runs=N; 转发 payload 含 param_ranges/batch_no
- GET /strategies/{id}/batches + /batches/{batch_no}/tasks → 200 批次/任务
- POST /strategies/{id}/live:
    无 best_params → 400 NO_BEST_PARAMS; 有 → 202 + 转发 mode=live
- 未认证 → 401

strategy_exec 转发 monkeypatch 为异步记录器, 不连真实 8001。
"""
import os
import sys

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
from server.services import script_strategy as svc  # noqa: E402
from server.tables import Strategy, StrategyTask, StrategyScript  # noqa: E402
from server.services.script_strategy._convert import json_dumps  # noqa: E402

UID = 990010003
USERNAME = f"ut_api_{UID}"

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
    {"key": "slow", "type": "int", "min": 1, "max": 3, "step": 1, "default": 2},
]


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _cleanup():
    """删除上次运行的测试数据 (按真实 DB user id 而非用户名后缀 UID)。

    v123 修正: 之前按 user_id=UID(990010003) 过滤, 但表中 user_id 是自增真实
    id, 该过滤永远不命中 → 每次运行都泄漏 strategy/strategy_task/strategy_script。
    """
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=USERNAME).first()
        uid = u.id if u else None
    finally:
        db.close()
    if uid is not None:
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


@pytest.fixture
def strategy_id(client, user_and_cleanup):
    """建一个脚本 + 策略, 返 strategy_id."""
    script_id = f"ut_api_script_{UID}"
    r = client.post("/api/script-strategy/scripts", json={
        "name": script_id, "code": "def init(self): pass", "params_schema": SCHEMA,
    }, headers=user_and_cleanup)
    assert r.status_code == 201, r.text
    r2 = client.post("/api/script-strategy/strategies", json={
        "name": f"api策略-{script_id}", "script_id": script_id,
    }, headers=user_and_cleanup)
    assert r2.status_code == 201, r2.text
    return r2.json()["strategy_id"]


def test_unauthorized_401(client):
    assert client.get("/api/script-strategy/strategies").status_code == 401


def test_strategy_crud_endpoints(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    # list
    r = client.get("/api/script-strategy/strategies", headers=h)
    assert r.status_code == 200
    assert any(s["strategy_id"] == strategy_id for s in r.json())
    # detail (含脚本)
    r = client.get(f"/api/script-strategy/strategies/{strategy_id}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"
    assert body["best_params"] is None
    assert body["script"]["params_schema"]
    # update
    r = client.put(f"/api/script-strategy/strategies/{strategy_id}",
                   json={"name": "改名", "status": "active"}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "改名"
    # delete
    r = client.delete(f"/api/script-strategy/strategies/{strategy_id}", headers=h)
    assert r.status_code == 204
    assert client.get(f"/api/script-strategy/strategies/{strategy_id}", headers=h).status_code == 404


def test_backtest_single_forwards_run_task(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    calls = []

    async def fake_forward(task_id, payload):
        calls.append(("run-task", task_id, payload))

    monkeypatch.setattr("server.api.script_strategy.strategies._forward_run_task", fake_forward)

    r = client.post(f"/api/script-strategy/strategies/{strategy_id}/backtest", json={
        "mode": "single", "stock_code": "600519.SH",
        "backtest_start_date": "20260101", "backtest_end_date": "20260131",
        "params": {"fast": 3, "slow": 2},
    }, headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["total_runs"] == 1
    assert body["mode"] == "single"
    assert body["metric"] == "sharpe"
    # 转发 payload 形状
    kind, task_id, payload = calls[0]
    assert kind == "run-task"
    assert payload["strategy_id"] == strategy_id
    assert payload["mode"] == "backtest"
    assert payload["params"] == {"fast": 3, "slow": 2}
    assert payload["task_id"] == task_id


def test_backtest_sweep_forwards_run_sweep(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    calls = []

    async def fake_forward(payload):
        calls.append(payload)

    monkeypatch.setattr("server.api.script_strategy.strategies._forward_run_sweep", fake_forward)

    r = client.post(f"/api/script-strategy/strategies/{strategy_id}/backtest", json={
        "mode": "sweep", "stock_code": "600519.SH",
        "backtest_start_date": "20260101", "backtest_end_date": "20260131",
        "param_ranges": {"fast": {"type": "int", "start": 1, "end": 3, "step": 1}},
        "metric": "sharpe", "concurrency": 2,
    }, headers=h)
    assert r.status_code == 202, r.text
    assert r.json()["total_runs"] == 3
    payload = calls[0]
    assert payload["strategy_id"] == strategy_id
    assert payload["batch_no"] is not None
    assert payload["param_ranges"]["fast"] == {"type": "int", "start": 1, "end": 3, "step": 1}
    assert len(payload["task_ids"]) == 3


def test_batches_and_batch_tasks_endpoints(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    async def noop(payload):
        return None
    monkeypatch.setattr("server.api.script_strategy.strategies._forward_run_sweep", noop)

    r = client.post(f"/api/script-strategy/strategies/{strategy_id}/backtest", json={
        "mode": "sweep", "stock_code": "600519.SH",
        "backtest_start_date": "20260101", "backtest_end_date": "20260131",
        "param_ranges": {"fast": {"type": "int", "start": 1, "end": 2, "step": 1}},
    }, headers=h)
    batch_no = r.json()["batch_no"]

    r = client.get(f"/api/script-strategy/strategies/{strategy_id}/batches", headers=h)
    assert r.status_code == 200
    batches = r.json()
    bb = next(x for x in batches if x["batch_no"] == batch_no)
    assert bb["task_count"] == 2
    assert bb["finished_count"] == 0

    r = client.get(
        f"/api/script-strategy/strategies/{strategy_id}/batches/{batch_no}/tasks", headers=h)
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 2
    assert all(t["mode"] == "backtest" for t in tasks)


def test_live_gate_400_no_best_params(client, user_and_cleanup, strategy_id):
    h = user_and_cleanup
    r = client.post(f"/api/script-strategy/strategies/{strategy_id}/live",
                    json={"stock_code": "600519.SH"}, headers=h)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_BEST_PARAMS"


def test_live_success_forwards_run_task(client, user_and_cleanup, strategy_id, monkeypatch):
    h = user_and_cleanup
    Strategy.update_one(
        {"best_params": json_dumps({"fast": 5, "slow": 2})}, strategy_id=strategy_id)
    calls = []

    async def fake_forward(task_id, payload):
        calls.append((task_id, payload))

    monkeypatch.setattr("server.api.script_strategy.strategies._forward_run_task", fake_forward)

    r = client.post(f"/api/script-strategy/strategies/{strategy_id}/live",
                    json={"stock_code": "600519.SH"}, headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["mode"] == "live"
    task_id, payload = calls[0]
    assert payload["strategy_id"] == strategy_id
    assert payload["mode"] == "live"
    assert payload["params"] == {"fast": 5, "slow": 2}
    assert payload["task_id"] == task_id == body["task_id"]
