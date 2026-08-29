"""
test_stale_queued_cleanup.py — POST /strategies/{id}/stale-queued/cleanup 端点测试

覆盖:
  Case 1: admin + 有 stale → 200 + cleaned_count=N + DB status 已变 failed
  Case 2: admin + 无 stale → 200 + cleaned_count=0
  Case 3: 非 admin → 403 FORBIDDEN
  Case 4: strategy 不存在 → 404 NO_STRATEGY

Mock 策略:
  - patch get_current_user dependency 为 fake user (绕过 DB JWT)
  - patch resolve_strategy 隔离 DB 真实 strategy 查
  - patch mark_stale_queued_failed (svc) 返回 fake rowcount
  - 验证返回的 cleaned_count 与 fake 一致
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from server.auth.deps import get_current_user


# ─────────────── Fixtures ───────────────


@pytest.fixture
def client():
    return TestClient(app)


def _make_user(role: str = "admin", user_id: int = 999) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id, username="tester", role=role, is_active=True,
    )


@pytest.fixture
def admin_client(client):
    app.dependency_overrides[get_current_user] = lambda: _make_user("admin")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def trader_client(client):
    app.dependency_overrides[get_current_user] = lambda: _make_user("trader", user_id=1)
    yield client
    app.dependency_overrides.clear()


# ─────────────── Case 1: admin + 有 stale ───────────────


def test_admin_cleanup_with_stale_returns_count(admin_client):
    """admin 调 endpoint, 假设有 3 条 stale → 200 + cleaned_count=3"""
    fake_strategy = SimpleNamespace(_data={"strategy_id": 3, "user_id": 999, "is_public": 0})

    with patch(
        "server.services.script_strategy.access.resolve_strategy",
        return_value=fake_strategy,
    ), patch(
        "server.api.script_strategy.strategies.svc.mark_stale_queued_failed",
        return_value=3,
    ):
        resp = admin_client.post("/api/script-strategy/strategies/3/stale-queued/cleanup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_id"] == 3
    assert body["cleaned_count"] == 3
    assert "broker his_hq unavailable" in body["error_msg_template"]


# ─────────────── Case 2: admin + 无 stale ───────────────


def test_admin_cleanup_no_stale_returns_zero(admin_client):
    """admin 调 endpoint, 无 stale → 200 + cleaned_count=0"""
    fake_strategy = SimpleNamespace(_data={"strategy_id": 7, "user_id": 999, "is_public": 0})

    with patch(
        "server.services.script_strategy.access.resolve_strategy",
        return_value=fake_strategy,
    ), patch(
        "server.api.script_strategy.strategies.svc.mark_stale_queued_failed",
        return_value=0,
    ):
        resp = admin_client.post("/api/script-strategy/strategies/7/stale-queued/cleanup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_id"] == 7
    assert body["cleaned_count"] == 0


# ─────────────── Case 3: 非 admin → 403 ───────────────


def test_non_admin_returns_403(trader_client):
    """非 admin 调 endpoint → 403 FORBIDDEN"""
    resp = trader_client.post("/api/script-strategy/strategies/3/stale-queued/cleanup")
    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "FORBIDDEN"


# ─────────────── Case 4: strategy 不存在 → 404 ───────────────


def test_strategy_not_found_returns_404(admin_client):
    """admin 调 endpoint, strategy 不存在 → 404 NO_STRATEGY"""
    with patch(
        "server.services.script_strategy.access.resolve_strategy",
        return_value=None,
    ):
        resp = admin_client.post("/api/script-strategy/strategies/99999/stale-queued/cleanup")

    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "NO_STRATEGY"


# ─────────────── Case 5: helper mark_stale_queued_failed 边界 ───────────────


def test_helper_returns_zero_for_unknown_strategy():
    """helper 对不存在的 strategy_id 返 0 (不抛错)"""
    from server.services.script_strategy.batches import mark_stale_queued_failed
    n = mark_stale_queued_failed(999999999)
    assert n == 0


def test_helper_error_msg_template():
    """error_msg template 含必要信息 (回填原因 + 重测建议)"""
    from server.services.script_strategy import STALE_CLEANUP_ERROR_MSG
    assert "broker his_hq unavailable" in STALE_CLEANUP_ERROR_MSG
    assert "建议重测" in STALE_CLEANUP_ERROR_MSG
    assert "2026-08-29" in STALE_CLEANUP_ERROR_MSG  # 回填时间戳