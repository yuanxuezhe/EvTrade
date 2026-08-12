"""
test_cost_price_round4.py — cost_price 统一 4 位小数口径 (cost-price-round4)

覆盖 2 条边界 (写路径 + 读路径):
- reconcile 落库: broker avg_price 带 5-6 位小数 → 入库前 _round4
- _position_to_out_dict: WS position_update 序列化 cost_price 也 round 4 位

测试策略:
- reconcile 用 fake Session 记录 db.add(Position) 入参, monkeypatch _update_last_asset
  为 no-op (只测 positions 写路径, 不触碰资产表/quote 表)
- _position_to_out_dict 是纯函数, 直接构造 _FakeRow
"""
import pytest

from server.services import reconcile as reconcile_module
from server.services.reconcile import _apply_broker_data
from server.services.push.helpers import _position_to_out_dict


class _FakeQuery:
    """模拟 db.query(Model).delete()"""
    def delete(self):
        return None


class _FakeSession:
    """模拟 Session: 记录 db.add 的对象, query/commit 空实现"""
    def __init__(self):
        self.added = []

    def query(self, model):
        return _FakeQuery()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass


class _FakeRow:
    """模拟 ORM Row 的属性访问"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ─────────────── 写路径: reconcile 落库 ───────────────


def test_reconcile_write_rounds_cost_price_to_4(monkeypatch):
    """Given: broker avg_price=1.41914 (5 位)
    When:  _apply_broker_data 落库
    Then:  Position.cost_price == 1.4191 (4 位)
    """
    monkeypatch.setattr(reconcile_module, "_update_last_asset", lambda db: None)
    db = _FakeSession()

    positions = [{
        "stock_code": "600000",
        "stock_name": "",
        "last_vol": 100,
        "avl_vol": 100,
        "vol": 100,
        "cost_price": 1.41914,   # broker m_dOpenPrice 原始精度
    }]
    _apply_broker_data(db, "20260812", positions, [])

    assert len(db.added) == 1
    assert db.added[0].cost_price == 1.4191


def test_reconcile_write_rounds_6_decimals_to_4(monkeypatch):
    """真实案例: 0.763661 (6 位) → 0.7637"""
    monkeypatch.setattr(reconcile_module, "_update_last_asset", lambda db: None)
    db = _FakeSession()

    positions = [{
        "stock_code": "000001",
        "stock_name": "",
        "last_vol": 100,
        "avl_vol": 100,
        "vol": 100,
        "cost_price": 0.763661,
    }]
    _apply_broker_data(db, "20260812", positions, [])

    assert db.added[0].cost_price == 0.7637


# ─────────────── 读路径: WS 序列化 ───────────────


def test_position_to_out_dict_rounds_cost_price():
    """Given: DB cost_price=1.41914 (若未 round 的中间态)
    When:  _position_to_out_dict 序列化 (WS position_update)
    Then:  cost_price == 1.4191
    """
    row = _FakeRow(
        stock_code="600000",
        stock_name="",
        last_vol=100,
        avl_vol=100,
        vol=100,
        cost_price=1.41914,
        synced_at="2026-08-12 10:00:00",
        synced_from="pos_push",
    )
    out = _position_to_out_dict(row)
    assert out["cost_price"] == 1.4191
