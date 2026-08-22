"""
test_script_new.py — POST /api/script-strategy/scripts/new 端点测试

覆盖 3 个 case：
  Case 1: 无重名 → 创建 new_strategy, HTTP 201
  Case 2: new_strategy 已存在 → 创建 new_strategy01, HTTP 201
  Case 3: new_strategy + new_strategy01 都存在 → 创建 new_strategy02, HTTP 201

Mock 策略：
  1. patch get_current_user dependency 为 fake user（绕过 DB JWT 验证）
  2. patch svc.auto_create_script 隔离 DB，验证传参正确
  3. patch _load_default_template 隔离文件读取
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from server.auth.deps import get_current_user


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_user():
    u = SimpleNamespace(
        id=1,
        username="tester",
        role="trader",
        is_active=True,
    )
    return u


@pytest.fixture
def auth_client(client, fake_user):
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield client
    app.dependency_overrides.clear()


# ─────────────────── Case 1: 无重名 → new_strategy ───────────────────

def test_new_script_first(auth_client):
    """第一次创建 → name=new_strategy, HTTP 201"""
    fake_script = {"id": "new_strategy", "user_id": 1, "name": "new_strategy",
                   "code": "pass", "params_schema": [], "description": "",
                   "status": "active", "is_public": False}
    with patch(
        "server.api.script_strategy.scripts._load_default_template",
        return_value={"code": "pass", "params_schema": []},
    ), patch(
        "server.api.script_strategy.scripts.svc.auto_create_script",
        return_value=fake_script,
    ) as mock_create:
        resp = auth_client.post("/api/script-strategy/scripts/new")

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "new_strategy"
    # 验证 svc.auto_create_script 被正确调用
    mock_create.assert_called_once_with(user_id=1, code="pass", params_schema=[])


# ─────────────────── Case 2: new_strategy 已存在 → new_strategy01 ───────────────────

def test_new_script_second(auth_client):
    """new_strategy 已存在 → name=new_strategy01, HTTP 201"""
    fake_script = {"id": "new_strategy01", "user_id": 1, "name": "new_strategy01",
                   "code": "pass", "params_schema": [], "description": "",
                   "status": "active", "is_public": False}
    with patch(
        "server.api.script_strategy.scripts._load_default_template",
        return_value={"code": "pass", "params_schema": []},
    ), patch(
        "server.api.script_strategy.scripts.svc.auto_create_script",
        return_value=fake_script,
    ):
        resp = auth_client.post("/api/script-strategy/scripts/new")

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "new_strategy01"


# ─────────────────── Case 3: 前两个都存在 → new_strategy02 ───────────────────

def test_new_script_third(auth_client):
    """new_strategy + new_strategy01 都存在 → name=new_strategy02, HTTP 201"""
    fake_script = {"id": "new_strategy02", "user_id": 1, "name": "new_strategy02",
                   "code": "pass", "params_schema": [], "description": "",
                   "status": "active", "is_public": False}
    with patch(
        "server.api.script_strategy.scripts._load_default_template",
        return_value={"code": "pass", "params_schema": []},
    ), patch(
        "server.api.script_strategy.scripts.svc.auto_create_script",
        return_value=fake_script,
    ):
        resp = auth_client.post("/api/script-strategy/scripts/new")

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "new_strategy02"


# ─────────────────── Case 4: 未认证 → 401 ───────────────────

def test_new_script_unauthorized(client):
    """无 token → HTTP 401"""
    resp = client.post("/api/script-strategy/scripts/new")
    assert resp.status_code == 401
