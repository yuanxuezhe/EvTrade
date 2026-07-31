"""
test_pos_push_diff.py — REQ-PUSH-034 pos_push 无变化跳过落库与广播

覆盖 3 个场景:
- 无变化 → handle_pos_push 返回 None (不调 update_one, 不返回 position)
- 字段变化 → 走 update_one + 返回 {position: ...}
- 新建行 → 走 add_one + 返回 {position: ...} (不参与 diff)

测试策略:
- monkeypatch server.services.push.pos.Positions 的 query_by / add_one / update_one
  避免依赖真实 DB, 同时验证分支路径被正确走 / 跳过
"""
import pytest

from server.services.push import pos as pos_module
from server.services.push.pos import handle_pos_push


# ─────────────── Fixtures ───────────────


class _FakeRow:
    """模拟 Positions ORM Row, 用于 _fields_unchanged 的属性访问"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def fake_positions(monkeypatch):
    """替换 Positions 静态方法, 记录调用 + 用 _store 模拟 DB 行"""
    state = {
        "store": {},                # stock_code -> _FakeRow
        "add_one_calls": [],
        "update_one_calls": [],
        "query_by_calls": [],
    }

    def fake_query_by(field, value, limit=None):
        state["query_by_calls"].append({"field": field, "value": value})
        row = state["store"].get(value)
        return [row] if row else []

    def fake_add_one(data):
        state["add_one_calls"].append(data)
        row = _FakeRow(**data)
        state["store"][data["stock_code"]] = row
        return row

    def fake_update_one(data, **pk):
        state["update_one_calls"].append({"data": data, "pk": pk})
        stock_code = pk.get("stock_code")
        existing = state["store"].get(stock_code) or _FakeRow(stock_code=stock_code)
        for k, v in data.items():
            setattr(existing, k, v)
        state["store"][stock_code] = existing
        return existing

    monkeypatch.setattr(pos_module, "Positions", type(
        "FakePositions",
        (),
        {
            "query_by": staticmethod(fake_query_by),
            "add_one": staticmethod(fake_add_one),
            "update_one": staticmethod(fake_update_one),
        },
    ))

    return state


# ─────────────── Tests ───────────────


def test_no_change_returns_none_and_skips_update(fake_positions):
    """REQ-PUSH-034 Scenario: pos_push 4 字段与 DB 全等 → 返回 None

    Given: DB 已有 {stock_code:"X", last_vol:100, vol:100, avl_vol:100, cost_price:12.5}
    When:  broker 推 pos_push 同值
    Then:  handle_pos_push 返回 None
    And:   Positions.update_one 不被调用
    And:   Positions.add_one 不被调用
    """
    # arrange: 已有持仓行
    fake_positions["store"]["X"] = _FakeRow(
        stock_code="X",
        stock_name="",
        last_vol=100,
        vol=100,
        avl_vol=100,
        cost_price=12.5,
    )

    # act: broker 推相同快照
    row = {
        "stock_code": "X",
        "last_vol": 100,
        "vol": 100,
        "avl_vol": 100,
        "avg_price": 12.5,
    }
    result = handle_pos_push(db=None, row=row, ts="20260731120000")

    # assert
    assert result is None
    assert fake_positions["add_one_calls"] == []
    assert fake_positions["update_one_calls"] == []
    assert len(fake_positions["query_by_calls"]) == 1


def test_field_change_triggers_update_and_returns_position(fake_positions):
    """REQ-PUSH-034 Scenario: 字段变化 → 走 update_one + 返回 {position: ...}

    Given: DB 已有 {last_vol:100, vol:100, avl_vol:100, cost_price:12.5}
    When:  broker 推 {last_vol:100, vol:200, avl_vol:150, cost_price:13.0}
    Then:  Positions.update_one 被调用, 入参含新 4 字段
    And:   返回 dict 含 'position' key
    """
    fake_positions["store"]["X"] = _FakeRow(
        stock_code="X",
        stock_name="",
        last_vol=100,
        vol=100,
        avl_vol=100,
        cost_price=12.5,
    )

    row = {
        "stock_code": "X",
        "last_vol": 100,
        "vol": 200,           # 变化
        "avl_vol": 150,        # 变化
        "avg_price": 13.0,    # 变化
    }
    result = handle_pos_push(db=None, row=row, ts="20260731120000")

    assert isinstance(result, dict)
    assert "position" in result
    assert len(fake_positions["update_one_calls"]) == 1
    update = fake_positions["update_one_calls"][0]
    assert update["pk"] == {"stock_code": "X"}
    assert update["data"]["vol"] == 200
    assert update["data"]["avl_vol"] == 150
    assert update["data"]["cost_price"] == 13.0
    assert fake_positions["add_one_calls"] == []


def test_new_position_skips_diff_and_creates(fake_positions):
    """REQ-PUSH-034 Scenario: 新建行不走 diff, 走 add_one

    Given: DB 无 stock_code="X" 行
    When:  broker 推 pos_push {stock_code:"X", ...}
    Then:  Positions.add_one 被调用
    And:   返回 dict 含 'position' key
    """
    row = {
        "stock_code": "X",
        "last_vol": 100,
        "vol": 100,
        "avl_vol": 100,
        "avg_price": 12.5,
    }
    result = handle_pos_push(db=None, row=row, ts="20260731120000")

    assert isinstance(result, dict)
    assert "position" in result
    assert len(fake_positions["add_one_calls"]) == 1
    assert fake_positions["add_one_calls"][0]["stock_code"] == "X"
    assert fake_positions["add_one_calls"][0]["synced_from"] == "pos_push"
    assert fake_positions["update_one_calls"] == []


def test_cost_price_only_change_triggers_update(fake_positions):
    """4 字段任一变化都应触发更新, 这里单独测 cost_price 变化"""
    fake_positions["store"]["X"] = _FakeRow(
        stock_code="X",
        stock_name="",
        last_vol=100,
        vol=100,
        avl_vol=100,
        cost_price=12.5,
    )

    row = {
        "stock_code": "X",
        "last_vol": 100,
        "vol": 100,
        "avl_vol": 100,
        "avg_price": 13.0,   # cost_price 变化, vol/avl_vol/last_vol 不变
    }
    result = handle_pos_push(db=None, row=row, ts="20260731120000")

    assert isinstance(result, dict)
    assert len(fake_positions["update_one_calls"]) == 1
    assert fake_positions["update_one_calls"][0]["data"]["cost_price"] == 13.0


def test_missing_stock_code_returns_none(fake_positions):
    """stock_code 缺失 → 返回 None, 不触碰 Positions"""
    row = {"last_vol": 100, "vol": 100, "avl_vol": 100, "avg_price": 12.5}
    result = handle_pos_push(db=None, row=row, ts="20260731120000")

    assert result is None
    assert fake_positions["query_by_calls"] == []
    assert fake_positions["add_one_calls"] == []
    assert fake_positions["update_one_calls"] == []