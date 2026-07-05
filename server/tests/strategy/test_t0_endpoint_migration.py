"""
test_t0_endpoint_migration.py — T0 端点 JOIN 迁移单测（change strategy_trade task 8）

覆盖：
- resolve_t0_user_defs helper（3 用例：空 / 'T0' / 其他）
- apply_user_def_filter 加 db 参数 + 行为兼容（2 用例）
- 4 个端点 union 行为：t0_stats / t0_history / t0_exposure / t0_aggregate（5 用例）

📌 设计要点：
- user_def='T0' 现在 = {'T0'} ∪ {所有 type='t0' 策略的 id as str}
- 4 个端点对外响应 schema 不变
"""
import sys
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

# 让测试可独立运行（兼容 F:\EvTrade\server 下的本地导入风格）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from server.db import Base, engine, init_db, SessionLocal
from server.models.orm import Order, Trade, SysStatus
from server.models.user import User
from server.auth.security import hash_password, create_access_token
from server.services.strategy import repository as strat_repo


# ─────────────── Fixtures ───────────────


@pytest.fixture(autouse=True)
def fresh_db():
    """drop + init（策略表也跟着重建）"""
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    SessionLocal().close()


@pytest.fixture
def trader():
    """trader 用户 + JWT token"""
    db = SessionLocal()
    db.query(User).filter_by(username="t0_mig_trader").delete()
    u = User(username="t0_mig_trader", password_hash=hash_password("x"), role="trader")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.close()
    token = create_access_token({"sub": str(u.id), "role": "trader"})
    return {"id": u.id, "token": token}


@pytest.fixture
def client():
    """FastAPI TestClient"""
    from server.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ─────────────── 工具 ───────────────


def _mk_strategy(db, stock_code="600519.SH", type_="t0"):
    """Create strategy via repository（避免直接 INSERT 漏字段）"""
    s = strat_repo.create_strategy(db, user_id=1, stock_code=stock_code, type=type_)
    db.commit()
    db.refresh(s)
    return s


def _mk_order(db, order_no, user_def, order_type="23", price=10.0,
              volume=100, trd_date="20260706", stock_code="600519.SH", status="51"):
    o = Order(
        trd_date=trd_date, order_no=order_no, order_id=None,
        user_def=user_def, stock_code=stock_code, order_type=order_type,
        price_type=11, price=price, volume=volume,
        traded_volume=volume, traded_amount=price * volume, avg_price=price,
        status=status, status_msg="",
        order_time="2026-07-06 10:00:00.000",
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _mk_trade(db, trade_id, order_no, order_type="23", price=10.0,
              volume=100, trd_date="20260706", stock_code="600519.SH"):
    t = Trade(
        trd_date=trd_date, order_no=order_no, trade_id=trade_id,
        stock_code=stock_code, order_type=order_type,
        price=price, volume=volume, amount=price * volume,
        trade_time="2026-07-06 10:00:00.000",
        created_at=datetime.now(),
    )
    db.add(t)
    db.commit()
    return t


# ─────────────── resolve_t0_user_defs unit tests ───────────────


def test_resolve_t0_user_defs_empty_returns_none():
    """user_def='' → None（全部）"""
    from server.services.t0.aggregators import resolve_t0_user_defs
    db = SessionLocal()
    try:
        assert resolve_t0_user_defs(db, "") is None
        assert resolve_t0_user_defs(db, None) is None  # 兼容 None
    finally:
        db.close()


def test_resolve_t0_user_defs_T0_includes_strategy_ids():
    """user_def='T0' → {'T0'} ∪ 所有 type='t0' 策略 id（不含 general）"""
    from server.services.t0.aggregators import resolve_t0_user_defs
    db = SessionLocal()
    try:
        s_t0_a = _mk_strategy(db, "600519.SH", "t0")
        s_t0_b = _mk_strategy(db, "000001.SZ", "t0")
        s_general = _mk_strategy(db, "300750.SZ", "general")
        result = resolve_t0_user_defs(db, "T0")
        assert "T0" in result
        assert str(s_t0_a.id) in result
        assert str(s_t0_b.id) in result
        assert str(s_general.id) not in result  # general 不计入
        assert len(result) == 3
    finally:
        db.close()


def test_resolve_t0_user_defs_other_returns_literal():
    """user_def='CUSTOM' → {'CUSTOM'}（不 JOIN 策略表）"""
    from server.services.t0.aggregators import resolve_t0_user_defs
    db = SessionLocal()
    try:
        # 即使有策略，CUSTOM 也不会匹配任何 strategy id
        _mk_strategy(db, "600519.SH", "t0")
        result = resolve_t0_user_defs(db, "CUSTOM")
        assert result == {"CUSTOM"}
    finally:
        db.close()


# ─────────────── apply_user_def_filter 兼容 + 新行为 ───────────────


def test_apply_user_def_filter_with_db_unions_manual_and_strategy():
    """传 db 时：T0 字面 + type='t0' 策略单 → 联合"""
    from server.services.t0.aggregators import apply_user_def_filter
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_strategy(db, "600519.SH", "general")  # 不应计入
        o1 = _mk_order(db, "O1", "T0")
        o2 = _mk_order(db, "O2", str(s.id))
        _mk_order(db, "O3", "99")  # 普通单，不应计入
        _mk_trade(db, "T1", "O1")
        _mk_trade(db, "T2", "O2")
        _mk_trade(db, "T3", "O3")
        orders = db.query(Order).all()
        trades = db.query(Trade).all()
        f_orders, f_trades = apply_user_def_filter(orders, trades, "T0", db=db)
        order_nos = {o.order_no for o in f_orders}
        assert order_nos == {"O1", "O2"}
        trade_nos = {t.order_no for t in f_trades}
        assert trade_nos == {"O1", "O2"}
        # trades 数量也是 2（O3 不在）
        assert len(f_trades) == 2
    finally:
        db.close()


def test_apply_user_def_filter_legacy_without_db():
    """无 db 入参 → 字面匹配（向后兼容旧测试）"""
    from server.services.t0.aggregators import apply_user_def_filter
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0")
        _mk_order(db, "O2", str(s.id))
        orders = db.query(Order).all()
        trades = db.query(Trade).all()
        # db=None → 只匹配字面 'T0'（不含策略单 O2）
        f_orders, _ = apply_user_def_filter(orders, trades, "T0")
        assert {o.order_no for o in f_orders} == {"O1"}
    finally:
        db.close()


# ─────────────── 端点集成测试 ───────────────


def test_t0_stats_endpoint_includes_t0_strategy_orders(client, trader):
    """t0-stats t0_only=true → T0 手动单 + T0 策略单 联合计入"""
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0", volume=100)
        _mk_order(db, "O2", str(s.id), volume=200)
        _mk_order(db, "O3", "99", volume=300)  # 普通单，不计入
        _mk_trade(db, "T1", "O1", volume=100)
        _mk_trade(db, "T2", "O2", volume=200)
        _mk_trade(db, "T3", "O3", volume=300)
    finally:
        db.close()
    res = client.get("/api/orders/t0-stats/600519.SH?trd_date=20260706&t0_only=true",
                     headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    # T0 + T0 策略单 = 100 + 200 = 300
    assert data["today_buy_volume"] == 300
    assert data["order_count"] == 2


def test_t0_stats_endpoint_t0_only_false_returns_all(client, trader):
    """t0-stats t0_only=false → 全部 3 单都计入"""
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0", volume=100)
        _mk_order(db, "O2", str(s.id), volume=200)
        _mk_order(db, "O3", "99", volume=300)
        _mk_trade(db, "T1", "O1", volume=100)
        _mk_trade(db, "T2", "O2", volume=200)
        _mk_trade(db, "T3", "O3", volume=300)
    finally:
        db.close()
    res = client.get("/api/orders/t0-stats/600519.SH?trd_date=20260706&t0_only=false",
                     headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    # 全部 3 单 = 100 + 200 + 300 = 600
    assert data["today_buy_volume"] == 600
    assert data["order_count"] == 3


def test_t0_history_endpoint_includes_t0_strategy_trades(client, trader):
    """t0-history t0_only=true → T0 + T0 策略单的 trade 都计入"""
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0", volume=100)
        _mk_order(db, "O2", str(s.id), volume=200)
        _mk_order(db, "O3", "99", volume=300)
        _mk_trade(db, "T1", "O1", volume=100)
        _mk_trade(db, "T2", "O2", volume=200)
        _mk_trade(db, "T3", "O3", volume=300)
    finally:
        db.close()
    res = client.get("/api/orders/t0-history/600519.SH?days=30&t0_only=true",
                     headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    # trade_count: 仅 O1 + O2（不含 O3）
    total_trades = sum(p["trade_count"] for p in data["points"])
    assert total_trades == 2


def test_t0_exposure_endpoint_includes_t0_strategy_orders(client, trader):
    """t0-exposure user_def='T0' 默认包含 T0 策略单"""
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0", volume=1000)
        _mk_order(db, "O2", str(s.id), volume=2000)
        _mk_order(db, "O3", "99", volume=500)  # 普通单，不计入
        _mk_trade(db, "T1", "O1", volume=1000)
        _mk_trade(db, "T2", "O2", volume=2000)
        _mk_trade(db, "T3", "O3", volume=500)
    finally:
        db.close()
    res = client.get("/api/orders/t0-exposure?trd_date=20260706",
                     headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    # buy_volume = 1000 + 2000 = 3000（不含 O3）
    assert data["totals"]["buy_volume"] == 3000
    assert data["totals"]["net_volume"] == 3000
    # user_def 响应字段保留
    assert data["user_def"] == "T0"


def test_t0_aggregate_endpoint_includes_t0_strategy_orders(client, trader):
    """t0-aggregate user_def='T0' → 累计仅含 T0 + T0 策略单"""
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0", volume=100)
        _mk_order(db, "O2", str(s.id), volume=200)
        _mk_order(db, "O3", "99", volume=300)  # 不应计入
        _mk_trade(db, "T1", "O1", volume=100)
        _mk_trade(db, "T2", "O2", volume=200)
        _mk_trade(db, "T3", "O3", volume=300)
    finally:
        db.close()
    res = client.get("/api/orders/t0-aggregate?days=30",
                     headers=_auth(trader["token"]))
    assert res.status_code == 200
    data = res.json()
    summary = data["summary"]
    # trade_count / order_count 都只统计 T0 + T0 策略单
    assert summary["trade_count"] == 2
    assert summary["order_count"] == 2
    # total_buy_amount = 100*10 + 200*10 = 3000.0
    assert summary["total_buy_amount"] == 3000.0
    assert data["user_def"] == "T0"


def test_response_schema_unchanged_after_migration(client, trader):
    """迁移后 4 个端点的响应 schema 字段名/类型保持不变"""
    db = SessionLocal()
    try:
        s = _mk_strategy(db, "600519.SH", "t0")
        _mk_order(db, "O1", "T0", volume=100)
        _mk_order(db, "O2", str(s.id), volume=200)
        _mk_trade(db, "T1", "O1", volume=100)
        _mk_trade(db, "T2", "O2", volume=200)
    finally:
        db.close()
    headers = _auth(trader["token"])

    # t0-stats
    r1 = client.get("/api/orders/t0-stats/600519.SH?trd_date=20260706&t0_only=true", headers=headers)
    assert set(r1.json().keys()) == {
        "trd_date", "stock_code", "today_buy_volume", "today_sell_volume",
        "today_buy_amount", "today_sell_amount", "realized_pnl", "cost_basis",
        "position_volume", "position_cost_total", "unrealized_pnl", "total_pnl",
        "order_count", "trade_count", "open_order_count",
    }

    # t0-history
    r2 = client.get("/api/orders/t0-history/600519.SH?days=30&t0_only=true", headers=headers)
    assert set(r2.json().keys()) == {
        "stock_code", "days", "points", "total_realized",
        "total_return_rate", "win_days", "total_days",
    }

    # t0-exposure
    r3 = client.get("/api/orders/t0-exposure?trd_date=20260706", headers=headers)
    assert set(r3.json().keys()) == {"trd_date", "user_def", "positions", "totals"}

    # t0-aggregate
    r4 = client.get("/api/orders/t0-aggregate?days=30", headers=headers)
    assert set(r4.json().keys()) == {"user_def", "days", "summary", "by_day", "by_stock"}