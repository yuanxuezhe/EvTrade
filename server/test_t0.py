"""
test_t0.py — 验证 T0 配平 + 费率
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from decimal import Decimal
from db import SessionLocal
from models.orm import FeeConfig
from services.t0 import (
    get_fee_config, calc_t0_volume, calc_net_amount, round_to_lot, LOT_SIZE,
)


@pytest.fixture(autouse=True)
def fresh_db():
    from db import Base, engine, init_db
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


# ──── 配平系数 ────

def test_calc_t0_volume_default_coefficient():
    """coefficient=1.0 → 不变"""
    assert calc_t0_volume(1100, 1.0, "BUY") == 1100
    assert calc_t0_volume(1100, 1.0, "SELL") == 1100


def test_calc_t0_volume_partial_lot_rounds_down_buy():
    """买单：不足 100 向下取整"""
    assert calc_t0_volume(1050, 1.0, "BUY") == 1000
    assert calc_t0_volume(99, 1.0, "BUY") == 0


def test_calc_t0_volume_partial_lot_rounds_up_sell():
    """卖单：不足 100 向上取整"""
    assert calc_t0_volume(1050, 1.0, "SELL") == 1100


def test_calc_t0_volume_with_coefficient():
    """配平系数 < 1.0 → 减配"""
    # 1000 * 0.5 = 500 → 500
    assert calc_t0_volume(1000, 0.5, "BUY") == 500
    # 1000 * 0.55 = 550 → 500
    assert calc_t0_volume(1000, 0.55, "BUY") == 500
    # 1000 * 1.2 = 1200
    assert calc_t0_volume(1000, 1.2, "BUY") == 1200


def test_calc_t0_volume_zero_target():
    assert calc_t0_volume(0, 1.0, "BUY") == 0
    assert calc_t0_volume(-100, 1.0, "BUY") == 0


# ──── 整手工具 ────

def test_round_to_lot():
    assert round_to_lot(1100, "BUY") == 1100
    assert round_to_lot(1050, "BUY") == 1000
    assert round_to_lot(1050, "SELL") == 1100


# ──── 费率 ────

def test_get_fee_config_default():
    """默认 commission_rate = 0.0001 (万一)"""
    cfg = get_fee_config()
    assert cfg.commission_rate == 0.0001


def test_calc_commission_below_min():
    """小金额也按万一收（无 min）"""
    cfg = FeeConfig(commission_rate=0.0001, stamp_tax_rate=0.001)
    # gross = 10 * 100 = 1000, commission = 0.1
    gross, net = calc_net_amount(10.0, 100, cfg, "BUY")
    assert gross == 1000.0
    assert net == pytest.approx(1000.1)
    assert net - gross == pytest.approx(0.1)  # 买方向 net > gross（付手续费）


def test_calc_commission_above_min():
    cfg = FeeConfig(commission_rate=0.0001, stamp_tax_rate=0.001)
    # amount = price * volume = 10 * 10000 = 100000
    # commission = 100000 * 0.0001 = 10.0
    gross, net = calc_net_amount(10.0, 10000, cfg, "BUY")
    assert gross == 100000.0
    # net = gross + commission
    assert net == 100010.0


def test_calc_net_amount_buy():
    """买：net = gross + commission"""
    cfg = FeeConfig(commission_rate=0.0001, stamp_tax_rate=0.001)
    gross, net = calc_net_amount(10.0, 1000, cfg, "BUY")
    assert gross == 10000.0
    # commission = 1.0
    assert net == 10001.0


def test_calc_net_amount_sell_with_stamp_tax():
    """卖：net = gross - commission - stamp_tax"""
    cfg = FeeConfig(commission_rate=0.0001, stamp_tax_rate=0.001)
    gross, net = calc_net_amount(10.0, 1000, cfg, "SELL")
    assert gross == 10000.0
    # commission = 1, stamp = 10
    assert net == 10000.0 - 1.0 - 10.0  # = 9989
