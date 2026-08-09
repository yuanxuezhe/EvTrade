"""
test_repository.py — strategy repository CRUD 单测

覆盖：
- create_strategy 含嵌套 regimes + grids
- get / list / update / delete strategy
- cascade delete：删 Strategy → regimes/grids/audits 全部清空
- JSON 字段 round-trip（required_flags / exclude_flags）
- increment_fired_count 累加正确
- write_audit 写入 + list_audits 查询
"""
import pytest


@pytest.fixture
def db():
    """每个 test 独立 Session，且 test 开始前清空 strategy 系列表。

    为什么不走 SAVEPOINT：cascade delete 测试需要真实 commit 才能触发
    SQLite FK ON DELETE CASCADE；SAVEPOINT 内部 commit 不会触发 DB 层 cascade。
    """
    from server.db import SessionLocal
    from sqlalchemy import text
    s = SessionLocal()
    # test 开始前清空（顺序：审计 → grid → regime → strategy，避开 FK 约束）
    s.execute(text("DELETE FROM strategy_audit"))
    s.execute(text("DELETE FROM strategy_grid"))
    s.execute(text("DELETE FROM strategy_regime"))
    s.execute(text("DELETE FROM strategy"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_create_strategy_with_nested(db):
    from server.services.strategy.repository import create_strategy, get_strategy
    s = create_strategy(
        db, user_id=1,
        stock_code="600519.SH",
        type="t0",
        reference_price=1820.0,
        base_volume=100,
        regimes=[
            {
                "name": "多头",
                "priority": 10,
                "required_flags": ["ma_bullish", "macd金叉"],
                "exclude_flags": [],
                "base_volume": 200,
                "grids": [
                    {"direction": "buy", "step_offset": -10.0, "volume": 100, "priority": 1},
                    {"direction": "sell", "step_offset": 10.0, "volume": 200, "priority": 2},
                ],
            },
            {
                "name": "清仓",
                "priority": 1,
                "required_flags": [],
                "clear_position": True,
                "grids": [],
            },
        ],
    )
    db.commit()
    s2 = get_strategy(db, s.id, user_id=1)
    assert s2 is not None
    assert s2.type == "t0"
    assert len(s2.regimes) == 2
    # regimes 按 priority desc 排序（先多头=10，再清仓=1）
    assert s2.regimes[0].name == "多头"
    assert s2.regimes[0].get_required_flags() == ["ma_bullish", "macd金叉"]
    assert s2.regimes[0].base_volume == 200
    assert len(s2.regimes[0].grids) == 2
    assert s2.regimes[1].clear_position is True


def test_list_strategies_filter_by_type_and_status(db):
    from server.services.strategy.repository import create_strategy, list_strategies
    create_strategy(db, user_id=2, stock_code="A.SH", type="general", status="active")
    create_strategy(db, user_id=2, stock_code="B.SH", type="t0", status="active")
    create_strategy(db, user_id=2, stock_code="C.SH", type="t0", status="paused")
    db.commit()

    all_ = list_strategies(db, user_id=2)
    assert len(all_) == 3

    t0_only = list_strategies(db, user_id=2, type_="t0")
    assert len(t0_only) == 2
    assert all(s.type == "t0" for s in t0_only)

    active_t0 = list_strategies(db, user_id=2, type_="t0", status="active")
    assert len(active_t0) == 1
    assert active_t0[0].stock_code == "B.SH"

    # 不同 user 隔离
    other = list_strategies(db, user_id=999)
    assert other == []


def test_update_strategy_fields(db):
    from server.services.strategy.repository import create_strategy, get_strategy, update_strategy
    s = create_strategy(db, user_id=3, stock_code="X.SH")
    db.commit()
    update_strategy(db, s, status="paused", base_volume=500, note="pause for review")
    db.commit()
    s2 = get_strategy(db, s.id, user_id=3)
    assert s2.status == "paused"
    assert s2.base_volume == 500
    assert s2.note == "pause for review"


def test_cascade_delete_clears_all(db):
    from server.services.strategy.repository import (
        create_strategy, delete_strategy, get_strategy, list_audits, write_audit,
    )
    s = create_strategy(
        db, user_id=4, stock_code="Y.SH",
        regimes=[{"name": "R1", "grids": [{"direction": "buy", "volume": 100}]}],
    )
    db.commit()
    # 写 audit
    write_audit(db, strategy_id=s.id, trd_date="20260705", trigger_type="grid_buy")
    db.commit()
    assert len(list_audits(db, s.id, "20260705")) == 1

    delete_strategy(db, s)
    db.commit()
    assert get_strategy(db, s.id) is None
    assert list_audits(db, s.id, "20260705") == []


def test_increment_fired_count(db):
    from server.services.strategy.repository import (
        create_strategy, list_regimes, increment_fired_count,
    )
    s = create_strategy(
        db, user_id=5, stock_code="Z.SH",
        regimes=[{"name": "R", "grids": [{"direction": "buy", "volume": 100, "max_fires": 3}]}],
    )
    db.commit()
    g = list_regimes(db, s.id)[0].grids[0]
    assert g.fired_count == 0
    increment_fired_count(db, g)
    increment_fired_count(db, g)
    db.commit()
    assert g.fired_count == 2


def test_audit_round_trip_json(db):
    from server.services.strategy.repository import create_strategy, write_audit, list_audits
    s = create_strategy(db, user_id=6, stock_code="W.SH")
    db.commit()
    write_audit(
        db, strategy_id=s.id, trd_date="20260705", trigger_type="grid_buy",
        flags_active=["ma_bullish", "rsi_overbought"],
        current_price=12.34,
        position_vol=500,
        base_volume=100,
        action_payload={"order_type": "23", "volume": 100, "price": 12.30},
        order_no="10000023",
    )
    db.commit()
    rows = list_audits(db, s.id, "20260705")
    assert len(rows) == 1
    r = rows[0]
    assert r.get_flags_active() == ["ma_bullish", "rsi_overbought"]
    assert r.get_action_payload()["volume"] == 100
    assert r.order_no == "10000023"


def test_audit_reject_with_reason(db):
    from server.services.strategy.repository import create_strategy, write_audit, list_audits
    s = create_strategy(db, user_id=7, stock_code="V.SH")
    db.commit()
    write_audit(
        db, strategy_id=s.id, trd_date="20260705", trigger_type="grid_rejected",
        reject_reason="base_floor_protected",
        position_vol=100, base_volume=100,
    )
    db.commit()
    r = list_audits(db, s.id, "20260705")[0]
    assert r.reject_reason == "base_floor_protected"
    assert r.order_no is None  # 拒触发无 order_no