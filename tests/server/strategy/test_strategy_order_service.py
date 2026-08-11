"""
test_strategy_order_service.py — 策略下单母单 service 层单测 (v126 change task 6.2)

覆盖:
- create_strategy_order: best_params 非空才可建; NO_STRATEGY 权限门禁
- list_strategy_orders: 列我的 / admin 全部; 含 children_count + strategy_name
- get_strategy_order: 不可见 → None
- start_strategy_order: stopped→running + run_count+1 + active_task_id; closed/running 不可 start; 无 best_params 拒
- stop_strategy_order: running→stopped + active_task_id 清空 + stop_url; 非 running 拒
- close_strategy_order: 终态 closed; running 拒; 关闭后不可再 start
- list_strategy_order_children: 子单过滤 strategy_type=2 + task_id 匹配
- build_start_forward_payload: 字段齐全, parent_task_id/strategy_name 透传
- require_strategy_order_access: 三档 (owner/admin/公开/不存在)

DB-backed (dev MySQL), 唯一 test 数据 + teardown 清理, 不做 drop_all。
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.services import script_strategy as svc  # noqa: E402
from server.services.script_strategy import scripts as scripts_svc  # noqa: E402
from server.services.script_strategy.errors import StrategyError  # noqa: E402
from server.services.script_strategy.strategy_orders import (  # noqa: E402
    STATUS_CLOSED, STATUS_RUNNING, STATUS_STOPPED,
)
from server.services.script_strategy.strategy_order_lifecycle import (  # noqa: E402
    build_start_forward_payload,
)
from server.services.script_strategy._convert import json_dumps  # noqa: E402
from server.tables import (  # noqa: E402
    Orders, Strategy, StrategyOrder, StrategyScript, StrategyTask,
)

UID = 990010002
UID2 = 990010003

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
    {"key": "slow", "type": "int", "min": 1, "max": 3, "step": 1, "default": 2},
]

_script_seq = [0]


def _new_script_id() -> str:
    _script_seq[0] += 1
    return f"ut_v126_{UID}_{_script_seq[0]}"


def _cleanup_user(user_id: int) -> None:
    """删除该测试用户全部 策略/task/脚本/母单/orders (幂等)."""
    # 母单 (先清, 因 strategy_order.user_id 索引)
    for so in StrategyOrder.query_by_fields({"user_id": user_id}):
        StrategyOrder.delete_one(id=so._data["id"])
    # 策略级联 task (拿到 task_id → 清该 task_id 的 orders 子单)
    for s in Strategy.query_by_fields({"user_id": user_id}):
        sid = s._data.get("strategy_id")
        for t in StrategyTask.query_by_fields({"strategy_id": sid}):
            tid = t._data.get("id")
            for o in Orders.query_by_fields({"task_id": tid, "strategy_type": 2}):
                Orders.delete_one(trd_date=o._data["trd_date"], order_no=o._data["order_no"])
            StrategyTask.delete_one(id=tid)
        Strategy.delete_one(strategy_id=sid)
    for sc in StrategyScript.query_by_fields({"user_id": user_id}):
        StrategyScript.delete_one(user_id=user_id, id=sc._data["id"])


@pytest.fixture(autouse=True)
def _clean(scope="function"):
    _cleanup_user(UID)
    _cleanup_user(UID2)
    yield
    _cleanup_user(UID)
    _cleanup_user(UID2)


@pytest.fixture
def strategy_ctx():
    """脚本 + 策略 (同一测试用户), 返回 dict. 不含 best_params."""
    script_id = _new_script_id()
    scripts_svc.create_script(UID, script_id, "def init(self): pass", SCHEMA)
    strat = svc.create_strategy(UID, f"ut策略-{script_id}", script_id, stock_code="600519.SH")
    return {"user_id": UID, "script_id": script_id, "strategy_id": strat["strategy_id"]}


def _set_best_params(strategy_id: int, params: dict) -> None:
    """模拟 strategy_exec 回测后写 best_params."""
    Strategy.update_one(
        {"best_params": json_dumps(params)},
        strategy_id=strategy_id,
    )


def _make_strategy_with_best(strategy_id: int, params: Optional[dict] = None) -> None:
    _set_best_params(strategy_id, params or {"fast": 3, "slow": 2})


# ─────────────── create_strategy_order ───────────────

def test_create_strategy_order_requires_best_params(strategy_ctx):
    """无 best_params → NO_BEST_PARAMS, 不建母单."""
    with pytest.raises(StrategyError) as ei:
        svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    assert ei.value.code == "NO_BEST_PARAMS"
    # 母单表无新行
    assert StrategyOrder.query_by_fields({"strategy_id": strategy_ctx["strategy_id"]}) == []


def test_create_strategy_order_happy_path(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    assert o["strategy_id"] == strategy_ctx["strategy_id"]
    assert o["user_id"] == UID
    assert o["stock_code"] == "600519.SH"
    assert o["status"] == STATUS_STOPPED
    assert o["run_count"] == 0
    assert o["active_task_id"] is None
    assert isinstance(o["task_id"], int) and o["task_id"] > 0


def test_create_strategy_order_permission_denied(strategy_ctx):
    """他人公开策略不可建母单 (FORBIDDEN)."""
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    # 设为公开 + owner 改 UID2
    Strategy.update_one(
        {"is_public": 1, "user_id": UID2},
        strategy_id=strategy_ctx["strategy_id"],
    )
    with pytest.raises(StrategyError) as ei:
        svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    assert ei.value.code == "FORBIDDEN"


def test_create_strategy_order_no_strategy():
    with pytest.raises(StrategyError) as ei:
        svc.create_strategy_order(99999999, UID)
    assert ei.value.code == "NO_STRATEGY"


# ─────────────── list / get / children ───────────────

def test_list_strategy_orders_basic(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    out = svc.list_strategy_orders(UID)
    assert any(d["id"] == o["id"] for d in out)
    mine = [d for d in out if d["id"] == o["id"]][0]
    assert mine["strategy_name"] is not None  # owner 看到完整策略名
    assert mine["children_count"] == 0


def test_list_strategy_orders_admin_sees_all(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    out = svc.list_strategy_orders(999, is_admin=True)
    assert any(d["id"] == o["id"] for d in out)


def test_list_strategy_orders_filters_by_user(strategy_ctx):
    """他人公开策略: 我 (UID) 建不了母单, 但我的母单列表里看不到别人的."""
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    out = svc.list_strategy_orders(UID + 1, is_admin=False)
    assert all(d["id"] != o["id"] for d in out)


def test_get_strategy_order_invisible(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    assert svc.get_strategy_order(o["id"], UID + 1, is_admin=False) is None


def test_get_strategy_order_admin_sees(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    d = svc.get_strategy_order(o["id"], 999, is_admin=True)
    assert d is not None and d["id"] == o["id"]


# ─────────────── start / stop / close ───────────────

def test_start_strategy_order_happy(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"], {"fast": 3, "slow": 2})
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    r = svc.start_strategy_order(o["id"], UID)
    assert r["status"] == STATUS_RUNNING
    assert r["active_task_id"] is not None
    assert r["forward_payload"]["parent_task_id"] == o["task_id"]
    assert r["forward_payload"]["mode"] == "live"
    assert r["forward_payload"]["strategy_name"]  # 非空 (策略名)


def test_start_strategy_order_running_blocked(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    svc.start_strategy_order(o["id"], UID)
    with pytest.raises(StrategyError) as ei:
        svc.start_strategy_order(o["id"], UID)
    assert ei.value.code == "STRATEGY_ORDER_INVALID_STATE"


def test_start_strategy_order_no_best_params(strategy_ctx):
    """建时可无 best_params (测试隔离), start 时再校验."""
    # 走另一策略 (无 best_params) — 但 create 会拒, 改用 direct DB 插入
    from datetime import datetime
    from server.repo.orders import next_seq
    _script_seq[0] += 1
    script_id = f"ut_v126_{UID}_{_script_seq[0]}"
    scripts_svc.create_script(UID, script_id, "def init(self): pass", SCHEMA)
    strat2 = svc.create_strategy(UID, f"ut策略-{script_id}", script_id, stock_code="600519.SH")
    # 直接插 1 行母单 (绕过 create 校验)
    now = datetime.now()
    row = StrategyOrder.add_one({
        "task_id": int(next_seq("strategy_order")),
        "user_id": UID,
        "strategy_id": strat2["strategy_id"],
        "stock_code": "600519.SH",
        "status": STATUS_STOPPED,
        "active_task_id": None,
        "run_count": 0,
        "last_started_at": None,
        "last_stopped_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    })
    with pytest.raises(StrategyError) as ei:
        svc.start_strategy_order(row._data["id"], UID)
    assert ei.value.code == "NO_BEST_PARAMS"


def test_start_strategy_order_closed_blocked(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    svc.close_strategy_order(o["id"], UID)
    with pytest.raises(StrategyError) as ei:
        svc.start_strategy_order(o["id"], UID)
    assert ei.value.code == "STRATEGY_ORDER_INVALID_STATE"


def test_stop_strategy_order_happy(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    svc.start_strategy_order(o["id"], UID)
    r = svc.stop_strategy_order(o["id"], UID)
    assert r["status"] == STATUS_STOPPED
    assert r["stop_url"] == "/internal/stop-task"


def test_stop_strategy_order_not_running(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    with pytest.raises(StrategyError) as ei:
        svc.stop_strategy_order(o["id"], UID)
    assert ei.value.code == "STRATEGY_ORDER_INVALID_STATE"


def test_close_strategy_order_happy(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    d = svc.close_strategy_order(o["id"], UID)
    assert d["status"] == STATUS_CLOSED
    assert d["closed_at"] is not None


def test_close_strategy_order_running_blocked(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    svc.start_strategy_order(o["id"], UID)
    with pytest.raises(StrategyError) as ei:
        svc.close_strategy_order(o["id"], UID)
    assert ei.value.code == "STRATEGY_ORDER_INVALID_STATE"


def test_run_count_increments(strategy_ctx):
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    # 第 1 次启停
    svc.start_strategy_order(o["id"], UID)
    svc.stop_strategy_order(o["id"], UID)
    # 第 2 次启动
    svc.start_strategy_order(o["id"], UID)
    d = svc.get_strategy_order(o["id"], UID)
    assert d["run_count"] == 2


# ─────────────── list_strategy_order_children ───────────────

def test_list_strategy_order_children_filters_by_strategy_type(strategy_ctx):
    """orders 行 strategy_type=2 才算子单; strategy_type=0/1 不算."""
    _make_strategy_with_best(strategy_ctx["strategy_id"])
    o = svc.create_strategy_order(strategy_ctx["strategy_id"], UID)
    # 直接插 2 行 strategy_type=2 子单 + 1 行 strategy_type=0 普通单
    from datetime import datetime
    now = datetime.now()
    # 用唯一 trd_date (now.strftime) + 短 order_no 避免 PK 撞号
    trd = now.strftime("%Y%m%d")
    base = now.microsecond % 100
    for i, st in enumerate((2, 2, 0)):
        Orders.add_one({
            "task_id": o["task_id"], "strategy_type": st,
            "stock_code": "600519.SH", "order_no": f"CH{base + i}{st}",
            "trd_date": trd, "status": "8", "order_flag": 0,
            "created_at": now, "updated_at": now,
        })
    children = svc.list_strategy_order_children(o["id"], UID)
    assert children is not None
    assert len(children) == 2  # 只 strategy_type=2 的


def test_list_strategy_order_children_not_found(strategy_ctx):
    assert svc.list_strategy_order_children(99999999, UID) is None


# ─────────────── build_start_forward_payload ───────────────

def test_build_start_forward_payload_fields():
    order = {"task_id": 42, "user_id": 7, "strategy_id": 3, "stock_code": "600519.SH"}
    strategy = {"script_id": "x", "name": "均线"}
    payload = build_start_forward_payload(order, strategy, {"fast": 3}, live_task_id=1001)
    assert payload["task_id"] == 1001
    assert payload["user_id"] == 7
    assert payload["strategy_id"] == 3
    assert payload["script_id"] == "x"
    assert payload["stock_code"] == "600519.SH"
    assert payload["mode"] == "live"
    assert payload["params"] == {"fast": 3}
    assert payload["parent_task_id"] == 42
    assert payload["strategy_name"] == "均线"


# ─────────────── access 门禁 ───────────────

def test_require_strategy_order_access_owner(strategy_ctx):
    from server.services.script_strategy.access import require_strategy_order_access
    row = require_strategy_order_access(strategy_ctx["strategy_id"], UID)
    assert row is not None


def test_require_strategy_order_access_admin(strategy_ctx):
    from server.services.script_strategy.access import require_strategy_order_access
    row = require_strategy_order_access(strategy_ctx["strategy_id"], 999, is_admin=True)
    assert row is not None


def test_require_strategy_order_access_public_denied(strategy_ctx):
    from server.services.script_strategy.access import require_strategy_order_access
    # 改 owner 为 UID2 + 公开
    Strategy.update_one(
        {"is_public": 1, "user_id": UID2},
        strategy_id=strategy_ctx["strategy_id"],
    )
    with pytest.raises(StrategyError) as ei:
        require_strategy_order_access(strategy_ctx["strategy_id"], UID)
    assert ei.value.code == "FORBIDDEN"


def test_require_strategy_order_access_not_found():
    from server.services.script_strategy.access import require_strategy_order_access
    with pytest.raises(StrategyError) as ei:
        require_strategy_order_access(99999999, UID)
    assert ei.value.code == "NO_STRATEGY"
