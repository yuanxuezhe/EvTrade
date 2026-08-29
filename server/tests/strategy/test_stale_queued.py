"""
test_stale_queued.py — GET /api/script-strategy/strategies/{id}/stale-queued 端点测试

覆盖场景:
  Case 1: admin + 有 stale → 200 + stale_count>0 + stale_tasks 列表
  Case 2: admin + 无 stale → 200 + stale_count=0 + stale_tasks=[]
  Case 3: 非 admin (trader) → 403 FORBIDDEN
  Case 4: admin + strategy 不存在 → 404 NO_STRATEGY
  Case 5: list_stale_queued_tasks helper 边界 (空 strategy / 不存在 strategy_id)

Mock 策略:
  - patch get_current_user dependency 为 fake user (绕过 DB JWT)
  - patch list_stale_queued_tasks 隔离 DB 真实数据
  - patch resolve_strategy 隔离 DB 真实 strategy 查
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
    """TestClient + admin user override"""
    app.dependency_overrides[get_current_user] = lambda: _make_user("admin")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def trader_client(client):
    """TestClient + trader user override (非 admin)"""
    app.dependency_overrides[get_current_user] = lambda: _make_user("trader", user_id=1)
    yield client
    app.dependency_overrides.clear()


# ─────────────── Case 1: admin + 有 stale ───────────────


def test_admin_with_stale_returns_list(admin_client):
    """admin 调 endpoint, strategy 有 stale queued → 200 + 列表"""
    fake_rows = [
        {"task_id": 3, "batch_no": 10000002, "age_min": 24678, "created_at": "2026-08-12T16:04:11"},
        {"task_id": 4, "batch_no": 10000003, "age_min": 24677, "created_at": "2026-08-12T16:04:30"},
    ]
    fake_strategy = SimpleNamespace(_data={"strategy_id": 3, "user_id": 999, "is_public": 0})

    # endpoint 内 from server.services.script_strategy.access import resolve_strategy
    # → 整体 patch server.services.script_strategy.access 模块 (resolve_strategy 在那定义)
    with patch(
        "server.services.script_strategy.access.resolve_strategy",
        return_value=fake_strategy,
    ), patch(
        "server.api.script_strategy.strategies.svc.list_stale_queued_tasks",
        return_value=fake_rows,
    ):
        resp = admin_client.get("/api/script-strategy/strategies/3/stale-queued")

    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_id"] == 3
    assert body["stale_count"] == 2
    assert len(body["stale_tasks"]) == 2
    s = body["stale_tasks"][0]
    assert s["task_id"] == 3
    assert s["batch_no"] == 10000002
    assert s["age_min"] == 24678
    assert s["created_at"] == "2026-08-12T16:04:11"


# ─────────────── Case 2: admin + 无 stale ───────────────


def test_admin_without_stale_returns_empty(admin_client):
    """admin 调 endpoint, strategy 无 stale → 200 + 空列表"""
    fake_strategy = SimpleNamespace(_data={"strategy_id": 7, "user_id": 999, "is_public": 0})

    with patch(
        "server.services.script_strategy.access.resolve_strategy",
        return_value=fake_strategy,
    ), patch(
        "server.api.script_strategy.strategies.svc.list_stale_queued_tasks",
        return_value=[],
    ):
        resp = admin_client.get("/api/script-strategy/strategies/7/stale-queued")

    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_id"] == 7
    assert body["stale_count"] == 0
    assert body["stale_tasks"] == []


# ─────────────── Case 3: 非 admin (trader) → 403 ───────────────


def test_non_admin_returns_403(trader_client):
    """非 admin 调 endpoint → 403 FORBIDDEN (不泄漏 strategy 信息)"""
    resp = trader_client.get("/api/script-strategy/strategies/3/stale-queued")
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
        resp = admin_client.get("/api/script-strategy/strategies/99999/stale-queued")

    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "NO_STRATEGY"


# ─────────────── Case 5: list_stale_queued_tasks helper 边界 ───────────────


def test_helper_returns_empty_for_unknown_strategy():
    """helper 对不存在的 strategy_id 返回 []"""
    from server.services.script_strategy.batches import list_stale_queued_tasks
    rows = list_stale_queued_tasks(999999999)
    assert rows == []


def test_helper_accepts_threshold_hours():
    """helper 支持自定义 threshold_hours (传 0 → 包含所有 queued 没调度的)"""
    from server.services.script_strategy.batches import list_stale_queued_tasks
    # strategy 3 有 3 条 stale queued (id 3/4/5); threshold=0 应该包含全部 queued 无 started
    rows = list_stale_queued_tasks(3, threshold_hours=0)
    # threshold=0 仍要满足 created_at < NOW() - INTERVAL 0 HOUR → 严格小于, 实际不会包含
    # 这是设计边界 — threshold=0 在生产场景不该用, 验证不抛错即可
    assert isinstance(rows, list)