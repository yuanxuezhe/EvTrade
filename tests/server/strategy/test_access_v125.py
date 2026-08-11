"""
test_access_v125.py — 策略可见性/权限 access 层单测 (v125)

覆盖:
- strategy_is_public: is_public 0/1 → False/True
- public_view: 精简视图不含 script/best_params
- resolve_strategy: owner / 他人公开 / 他人私有 / 不存在
- require_backtest_access: owner 放行; 他人公开 → BACKTEST_FORBIDDEN; 他人私有/不存在 → NO_STRATEGY

DB-backed (dev MySQL), 唯一 test 数据 + teardown 清理。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.services import script_strategy as svc  # noqa: E402
from server.services.script_strategy import scripts as scripts_svc  # noqa: E402
from server.services.script_strategy import access  # noqa: E402
from server.services.script_strategy.strategies import StrategyError  # noqa: E402
from server.tables import Strategy, StrategyTask, StrategyScript  # noqa: E402

UID = 990010005
UID2 = 990010006

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
]

_script_seq = [0]


def _new_script_id() -> str:
    _script_seq[0] += 1
    return f"ut_acc_{UID}_{_script_seq[0]}"


def _cleanup_user(user_id: int) -> None:
    for s in Strategy.query_by_fields({"user_id": user_id}):
        sid = s._data.get("strategy_id")
        for t in StrategyTask.query_by_fields({"strategy_id": sid}):
            StrategyTask.delete_one(id=t._data["id"])
        Strategy.delete_one(strategy_id=sid)
    for sc in StrategyScript.query_by_fields({"user_id": user_id}):
        StrategyScript.delete_one(user_id=user_id, id=sc._data["id"])


@pytest.fixture(autouse=True)
def _clean():
    _cleanup_user(UID)
    _cleanup_user(UID2)
    yield
    _cleanup_user(UID)
    _cleanup_user(UID2)


@pytest.fixture
def strategy_ctx():
    script_id = _new_script_id()
    scripts_svc.create_script(UID, script_id, "def init(self): pass", SCHEMA)
    strategy_id = _mk_strategy(UID, script_id, f"ut策略-{script_id}", "600519.SH")
    return {"user_id": UID, "script_id": script_id, "strategy_id": strategy_id}


def _mk_strategy(user_id: int, script_id: str, name: str, stock_code: str, is_public: int = 0) -> int:
    """直接插 strategy 行 (Task 2 自包含: create_strategy 的 stock_code 参数在 Task 3 才实现)."""
    from datetime import datetime
    now = datetime.now()
    row = Strategy.add_one({
        "user_id": user_id,
        "script_id": script_id,
        "name": name,
        "status": "draft",
        "is_public": is_public,
        "stock_code": stock_code,
        "best_params": None,
        "created_at": now,
        "updated_at": now,
    })
    return row._data.get("strategy_id")


# ─────────────── strategy_is_public / public_view ───────────────

def test_strategy_is_public_flag(strategy_ctx):
    row = Strategy.query_one(strategy_id=strategy_ctx["strategy_id"])
    assert access.strategy_is_public(row) is False
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    assert access.strategy_is_public(Strategy.query_one(strategy_id=strategy_ctx["strategy_id"])) is True


def test_public_view_lean(strategy_ctx):
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    row = Strategy.query_one(strategy_id=strategy_ctx["strategy_id"])
    v = access.public_view(row)
    assert v["strategy_id"] == strategy_ctx["strategy_id"]
    assert v["is_public"] is True
    assert v["stock_code"] == "600519.SH"
    assert "script" not in v
    assert "best_params" not in v


# ─────────────── resolve_strategy ───────────────

def test_resolve_owner_returns_row(strategy_ctx):
    assert access.resolve_strategy(strategy_ctx["strategy_id"], UID) is not None


def test_resolve_other_public_returns_row(strategy_ctx):
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    assert access.resolve_strategy(strategy_ctx["strategy_id"], UID2) is not None


def test_resolve_other_private_none(strategy_ctx):
    assert access.resolve_strategy(strategy_ctx["strategy_id"], UID2) is None


def test_resolve_missing_none():
    assert access.resolve_strategy(99999999, UID) is None


# ─────────────── require_backtest_access ───────────────

def test_require_owner_ok(strategy_ctx):
    assert access.require_backtest_access(strategy_ctx["strategy_id"], UID) is not None


def test_require_other_public_forbidden(strategy_ctx):
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    with pytest.raises(StrategyError) as ei:
        access.require_backtest_access(strategy_ctx["strategy_id"], UID2)
    assert ei.value.code == "BACKTEST_FORBIDDEN"


def test_require_other_private_no_strategy(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        access.require_backtest_access(strategy_ctx["strategy_id"], UID2)
    assert ei.value.code == "NO_STRATEGY"


def test_require_missing_no_strategy():
    with pytest.raises(StrategyError) as ei:
        access.require_backtest_access(99999999, UID)
    assert ei.value.code == "NO_STRATEGY"
