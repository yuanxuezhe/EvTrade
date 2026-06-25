"""
test_t0_aggregate.py — T0 敞口聚合 + 真实已实现算法

覆盖：
- calc_realized_pnl（4 用例）
- calc_commission_and_tax 含 min_commission 兜底（2 用例）
- calc_net_exposure（2 用例）
- aggregate_by_stock + 端点（2 用例）
- aggregate_by_day + summary（2 用例）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from datetime import datetime, timedelta

from db import Base, engine, init_db, SessionLocal
from models.orm import FeeConfig, Order, Position, Trade
from services.t0_aggregate import (
    calc_commission_and_tax,
    calc_realized_pnl,
    calc_net_exposure,
    aggregate_by_day,
    aggregate_by_stock,
    aggregate_summary,
    apply_user_def_filter,
)


# ──── Fixtures ────

@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    SessionLocal().close()


def _mk_fee_cfg(commission=0.0001, stamp_tax=0.001, min_commission=5.0):
    return FeeConfig(
        commission_rate=commission,
        stamp_tax_rate=stamp_tax,
        min_commission=min_commission,
    )


def _mk_trade(stock_code, order_no, order_type, price, volume, trd_date="20260619", trade_id="T1"):
    return Trade(
        trd_date=trd_date,
        order_no=order_no,
        trade_id=trade_id,
        stock_code=stock_code,
        order_type=order_type,
        price=price,
        volume=volume,
        amount=price * volume,
        trade_time="2026-06-19 10:00:00.000",  # v10: String(23)
        created_at=datetime.now(),
    )


def _mk_order(order_no, stock_code, order_type, price, volume, user_def="T0", status="51"):
    return Order(
        trd_date="20260619",
        order_no=order_no,
        order_id=None,
        user_def=user_def,
        stock_code=stock_code,
        order_type=order_type,
        price_type=11,
        price=price,
        volume=volume,
        traded_volume=volume,
        traded_amount=price * volume,
        avg_price=price,
        status=status,
        status_msg="",
        order_time="2026-06-19 10:00:00.000",  # v10: String(23)
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _mk_pos(stock_code, vol=0, cost_price=0.0):
    return Position(
        stock_code=stock_code,
        stock_name="",
        last_vol=vol,
        today_buy=0,
        today_sell=0,
        avl_vol=vol,
        vol=vol,
        cost_price=cost_price,
        synced_at=datetime.now(),
        synced_from="rpc_full",
    )


# ──── calc_commission_and_tax ────

def test_commission_no_min_applied_when_above():
    """commission > min_commission 时不兜底"""
    cfg = _mk_fee_cfg(commission=0.0001, min_commission=5.0)
    # amount=100000 → commission = 10.0（> 5） → 用 10
    c, st = calc_commission_and_tax(100000.0, cfg, "BUY")
    assert c == 10.0
    assert st == 0.0  # 买入无印花税


def test_commission_min_applied_when_below():
    """commission < min_commission 时取 min"""
    cfg = _mk_fee_cfg(commission=0.0001, min_commission=5.0)
    # amount=1000 → commission = 0.1（< 5） → 兜底 5
    c, st = calc_commission_and_tax(1000.0, cfg, "SELL")
    assert c == 5.0
    assert st == 1.0  # 卖出印花税 1000 * 0.001


def test_stamp_tax_only_sell():
    cfg = _mk_fee_cfg()
    # 买入印花税 = 0
    c1, st1 = calc_commission_and_tax(50000.0, cfg, "BUY")
    assert st1 == 0.0
    # 卖出印花税 = 50
    c2, st2 = calc_commission_and_tax(50000.0, cfg, "SELL")
    assert st2 == 50.0


# ──── calc_realized_pnl ────

def test_realized_basic_profit():
    """卖 1000 股 @ 10, 成本基准 9, 费率万一+千 1"""
    cfg = _mk_fee_cfg()
    trades = [_mk_trade("600519.SH", "O001", "24", 10.0, 1000)]
    r, c, st = calc_realized_pnl(trades, 9.0, cfg)
    # gross = 10*1000 - 9*1000 = 1000
    # commission = 10000 * 0.0001 = 1.0 → < 5 兜底 5
    # stamp_tax = 10000 * 0.001 = 10.0
    # realized = 1000 - 5 - 10 = 985
    assert r == 985.0
    assert c == 5.0
    assert st == 10.0


def test_realized_basic_loss():
    cfg = _mk_fee_cfg()
    trades = [_mk_trade("600519.SH", "O001", "24", 9.0, 1000)]
    r, c, st = calc_realized_pnl(trades, 10.0, cfg)
    # gross = 9*1000 - 10*1000 = -1000
    # realized = -1000 - 5 - 9 = -1014
    assert r == -1014.0


def test_realized_empty_returns_zero():
    cfg = _mk_fee_cfg()
    r, c, st = calc_realized_pnl([], 10.0, cfg)
    assert (r, c, st) == (0.0, 0.0, 0.0)


def test_realized_no_cost_basis_only_fees():
    """无成本基准（未持仓）→ realized = -commission - stamp_tax"""
    cfg = _mk_fee_cfg()
    trades = [_mk_trade("600519.SH", "O001", "24", 10.0, 1000)]
    r, c, st = calc_realized_pnl(trades, 0.0, cfg)
    # gross = 10000 - 0 = 10000, realized = 10000 - 5 - 10 = 9985
    assert r == 9985.0


def test_realized_multi_trades():
    """多笔卖单合并算"""
    cfg = _mk_fee_cfg()
    trades = [
        _mk_trade("X", "O1", "24", 10.0, 500, trade_id="T1"),
        _mk_trade("X", "O2", "24", 11.0, 500, trade_id="T2"),
    ]
    r, c, st = calc_realized_pnl(trades, 10.0, cfg)
    # gross = (10*500 + 11*500) - 10*1000 = 10500 - 10000 = 500
    # commission = 10500*0.0001 = 1.05 → 兜底 5
    # stamp_tax = 10500*0.001 = 10.5
    # realized = 500 - 5 - 10.5 = 484.5
    assert r == 484.5
    assert st == 10.5


# ──── calc_net_exposure ────

def test_net_exposure_basic():
    orders = [
        _mk_order("O1", "X", "23", 10.0, 1000, status="51"),  # 买成
        _mk_order("O2", "X", "24", 11.0, 800, status="51"),   # 卖成
    ]
    trades = [
        _mk_trade("X", "O1", "23", 10.0, 1000),
        _mk_trade("X", "O2", "24", 11.0, 800),
    ]
    net, bv, sv, ba, sa = calc_net_exposure(orders, trades)
    assert net == 200   # 净买入 200
    assert bv == 1000
    assert sv == 800
    assert ba == 10000.0
    assert sa == 8800.0


def test_net_exposure_failed_order_excluded():
    """废单不计入 trade"""
    orders = [
        _mk_order("O1", "X", "23", 10.0, 1000, status="55"),  # 废单
        _mk_order("O2", "X", "24", 11.0, 500, status="51"),
    ]
    trades = [
        # O1 是废单无成交，O2 有成交
        _mk_trade("X", "O2", "24", 11.0, 500),
    ]
    net, bv, sv, ba, sa = calc_net_exposure(orders, trades)
    assert net == -500  # 净卖出 500
    assert bv == 0
    assert sv == 500


# ──── aggregate_by_stock ────

def test_aggregate_by_stock_multi_codes():
    cfg = _mk_fee_cfg()
    trades = [
        _mk_trade("600519.SH", "O1", "23", 180.0, 1000, trade_id="T1"),
        _mk_trade("600519.SH", "O2", "24", 182.0, 800, trade_id="T2"),
        _mk_trade("000001.SZ", "O3", "23", 12.0, 5000, trade_id="T3"),
        _mk_trade("000001.SZ", "O4", "24", 12.5, 4000, trade_id="T4"),
    ]
    orders = [
        _mk_order("O1", "600519.SH", "23", 180.0, 1000),
        _mk_order("O2", "600519.SH", "24", 182.0, 800),
        _mk_order("O3", "000001.SZ", "23", 12.0, 5000),
        _mk_order("O4", "000001.SZ", "24", 12.5, 4000),
    ]
    positions = {
        "600519.SH": _mk_pos("600519.SH", vol=200, cost_price=180.0),
        "000001.SZ": _mk_pos("000001.SZ", vol=1000, cost_price=12.0),
    }
    rows = aggregate_by_stock(trades, orders, positions, cfg)
    assert len(rows) == 2
    # 按 abs(net_amount) 降序：000001.SZ 的 net=1000*12-4000*12.5 = -38000；600519.SH net=200*180-800*182 = -97600
    assert rows[0]["stock_code"] == "600519.SH"
    assert rows[1]["stock_code"] == "000001.SZ"
    # 600519.SH: buy_vol=1000, sell_vol=800, net=200
    assert rows[0]["buy_volume"] == 1000
    assert rows[0]["sell_volume"] == 800
    assert rows[0]["net_volume"] == 200
    # realized = (182 - 180) * 800 - commission - stamp_tax
    # sell_amt = 182*800 = 145600
    # commission = 145600*0.0001 = 14.56 (no min)
    # stamp_tax = 145600*0.001 = 145.6
    # realized = 2*800 - 14.56 - 145.6 = 1600 - 160.16 = 1439.84
    assert rows[0]["realized_pnl"] == 1439.84


def test_aggregate_by_stock_no_position():
    """无持仓 → cost_basis=0，realized 只扣费"""
    cfg = _mk_fee_cfg()
    trades = [_mk_trade("X", "O1", "24", 10.0, 1000)]
    orders = [_mk_order("O1", "X", "24", 10.0, 1000)]
    rows = aggregate_by_stock(trades, orders, {}, cfg)
    assert len(rows) == 1
    # realized = 10000 - 5 - 10 = 9985
    assert rows[0]["realized_pnl"] == 9985.0


# ──── aggregate_by_day + summary ────

def test_aggregate_by_day_returns_sorted():
    cfg = _mk_fee_cfg()
    today = datetime.now()
    d1 = (today - timedelta(days=5)).strftime("%Y%m%d")
    d2 = today.strftime("%Y%m%d")
    trades = [
        _mk_trade("X", "O1", "23", 10.0, 1000, trd_date=d1, trade_id="T1"),
        _mk_trade("X", "O2", "24", 11.0, 500, trd_date=d1, trade_id="T2"),
        _mk_trade("Y", "O3", "24", 12.0, 500, trd_date=d2, trade_id="T3"),
    ]
    positions = {"X": _mk_pos("X", vol=500, cost_price=10.0), "Y": _mk_pos("Y", cost_price=10.0)}
    rows = aggregate_by_day(trades, positions, cfg)
    assert len(rows) == 2
    assert rows[0]["trd_date"] == d1
    assert rows[1]["trd_date"] == d2
    # d1 realized = (11-10)*500 - commission - stamp_tax = 500 - 5 - 5.5 = 489.5
    assert rows[0]["realized_pnl"] == 489.5


def test_summary_win_rate_and_return():
    cfg = _mk_fee_cfg()
    today = datetime.now()
    d1 = (today - timedelta(days=2)).strftime("%Y%m%d")
    d2 = (today - timedelta(days=1)).strftime("%Y%m%d")
    d3 = today.strftime("%Y%m%d")
    trades = [
        _mk_trade("X", "O1", "23", 10.0, 1000, trd_date=d1, trade_id="T1"),
        _mk_trade("X", "O2", "24", 11.0, 500, trd_date=d1, trade_id="T2"),  # 盈利
        _mk_trade("Y", "O3", "24", 9.0, 500, trd_date=d2, trade_id="T3"),   # 亏损
        _mk_trade("Z", "O4", "24", 11.0, 200, trd_date=d3, trade_id="T4"),   # 盈利
    ]
    positions = {
        "X": _mk_pos("X", cost_price=10.0),
        "Y": _mk_pos("Y", cost_price=10.0),
        "Z": _mk_pos("Z", cost_price=10.0),
    }
    by_day = aggregate_by_day(trades, positions, cfg)
    by_stock = aggregate_by_stock(trades, [], positions, cfg)
    summary = aggregate_summary(by_day, by_stock, [])
    assert summary["total_days"] == 3
    assert summary["win_days"] == 2
    assert summary["win_rate"] == pytest.approx(2 / 3, rel=1e-3)
    # return_rate = total_realized / total_buy_amount
    assert summary["return_rate"] > 0
    assert summary["trade_count"] == 4


# ──── apply_user_def_filter ────

def test_user_def_filter_only_T0():
    orders = [
        _mk_order("O1", "X", "23", 10.0, 1000, user_def="T0"),
        _mk_order("O2", "X", "23", 10.0, 500, user_def=""),     # 非 T0
        _mk_order("O3", "X", "24", 11.0, 800, user_def="T0"),
    ]
    trades = [
        _mk_trade("X", "O1", "23", 10.0, 1000, trade_id="T1"),
        _mk_trade("X", "O2", "23", 10.0, 500, trade_id="T2"),
        _mk_trade("X", "O3", "24", 11.0, 800, trade_id="T3"),
    ]
    f_orders, f_trades = apply_user_def_filter(orders, trades, "T0")
    assert len(f_orders) == 2
    order_nos = {o.order_no for o in f_orders}
    assert f_trades[0].order_no in order_nos
    assert all(t.order_no in order_nos for t in f_trades)
    assert len(f_trades) == 2


def test_user_def_filter_empty_returns_all():
    orders = [_mk_order("O1", "X", "23", 10.0, 1000, user_def="")]
    trades = [_mk_trade("X", "O1", "23", 10.0, 1000)]
    f_orders, f_trades = apply_user_def_filter(orders, trades, "")
    assert f_orders == orders
    assert f_trades == trades