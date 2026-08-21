"""
test_script_strategy_compile.py — POST /api/script-strategy/scripts/{id}/compile 端点测试

覆盖 3 个 case：
  Case 1: 语法正确 → HTTP 200 + {"ok": True, "warnings": []}
  Case 2: 语法错误（SyntaxError）→ HTTP 200 + {"ok": False, "error": {line, col, msg}}
  Case 3: script id 不存在 → HTTP 404 + SCRIPT_NOT_FOUND

Mock 策略：
  1. patch get_current_user dependency 为 fake user（绕过 DB JWT 验证）
  2. patch server.services.script_strategy.scripts.get_script 隔离 DB
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from server.auth.deps import get_current_user


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_user():
    """伪造已登录用户（用于 override get_current_user）"""
    u = SimpleNamespace(
        id=1,
        username="tester",
        role="trader",
        is_active=True,
    )
    return u


@pytest.fixture
def auth_client(client, fake_user):
    """TestClient + get_current_user 被 override 为 fake_user"""
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield client
    app.dependency_overrides.clear()


# ─────────────────────────── Case 1: 语法正确 ───────────────────────────

def test_compile_syntax_ok(auth_client):
    """语法正确的 Python 代码 → HTTP 200 + ok=True"""
    valid_code = "def foo():\n    pass\n"

    with patch(
        "server.api.script_strategy.scripts.svc.get_script",
        return_value={"id": "s1", "code": valid_code},
    ):
        resp = auth_client.post("/api/script-strategy/scripts/s1/compile")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "warnings": []}


# ─────────────────────────── Case 2: 语法错误 ───────────────────────────

def test_compile_syntax_error(auth_client):
    """缺少右括号的 def 语句 → HTTP 200 + ok=False + error{line,col,msg}"""
    bad_code = "def foo(:\n    pass\n"

    with patch(
        "server.api.script_strategy.scripts.svc.get_script",
        return_value={"id": "s2", "code": bad_code},
    ):
        resp = auth_client.post("/api/script-strategy/scripts/s2/compile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    err = body["error"]
    assert "line" in err and err["line"] >= 1
    assert "col" in err and err["col"] >= 1
    assert "msg" in err and isinstance(err["msg"], str) and err["msg"]


# ─────────────────────────── Case 3: script 不存在 ──────────────────────

def test_compile_script_not_found(auth_client):
    """script id 不存在 → HTTP 404 + SCRIPT_NOT_FOUND"""
    with patch(
        "server.services.script_strategy.scripts.get_script",
        return_value=None,
    ):
        resp = auth_client.post("/api/script-strategy/scripts/nonexistent/compile")

    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail", {}).get("code") == "SCRIPT_NOT_FOUND"
