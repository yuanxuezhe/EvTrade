"""
test_cost_price_round4.py — cost_price 按证券 scale 保留精度 (cost-price-scale)

覆盖 2 条边界 (写路径 + 读路径):
- reconcile 落库: broker avg_price 带 5-6 位小数 → 入库前按 stock.scale round
  (scale=2 → 1.41914→1.42; scale=3 → 0.763661→0.764)
- _position_to_out_dict: WS position_update 序列化 cost_price 也按 scale round

测试策略:
- monkeypatch get_stock_scale (写路径在 reconcile 命名空间, 读路径在 helpers 命名空间),
  避免触真实 DB — 与 test_pos_push_diff 的 hermetic 约定一致
- reconcile 用 fake Session 记录 db.add(Position) 入参, monkeypatch _update_last_asset no-op
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


class _FakePositionsUpsert:
    """记录 Positions.upsert_one 的调用参数，供测试断言"""
    recorded = []

    @classmethod
    def upsert_one(cls, data, **pk):
        cls.recorded.append((data, pk))
        # 验证 cost_price 已正确 round（这是测试的核心断言）
        cost_price = data.get("cost_price")
        if cost_price is not None and cost_price != round(cost_price, 4):
            raise AssertionError(
                f"cost_price not rounded: got {cost_price!r}, "
                f"expected {round(cost_price, 4)!r}"
            )


class _FakeRow:
    """模拟 ORM Row 的属性访问"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# scale 映射: 600000(A股)=2 / 000001(ETF)=3
_SCALE_MAP = {"600000": 2, "000001": 3}


def _fake_scale(db=None, stock_code=""):
    return _SCALE_MAP.get(stock_code, 2)


# ─────────────── 写路径: reconcile 落库 ───────────────


def test_reconcile_write_rounds_cost_price_by_scale_2(monkeypatch):
    """Given: broker avg_price=1.41914 (5 位), stock 600000 scale=2 (A股)
    When:  _apply_broker_data 落库
    Then:  Position.cost_price == 1.42
    """
    monkeypatch.setattr(reconcile_module, "_update_last_asset", lambda db: None)
    monkeypatch.setattr(reconcile_module, "get_stock_scale", _fake_scale)
    monkeypatch.setattr(reconcile_module.Positions, "upsert_one", _FakePositionsUpsert.upsert_one)
    _FakePositionsUpsert.recorded.clear()
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

    assert len(_FakePositionsUpsert.recorded) == 1
    data, pk = _FakePositionsUpsert.recorded[0]
    assert data["cost_price"] == 1.42


def test_reconcile_write_rounds_cost_price_by_scale_3(monkeypatch):
    """Given: broker avg_price=0.763661 (6 位), stock 000001 scale=3 (ETF)
    Then:  Position.cost_price == 0.764
    """
    monkeypatch.setattr(reconcile_module, "_update_last_asset", lambda db: None)
    monkeypatch.setattr(reconcile_module, "get_stock_scale", _fake_scale)
    monkeypatch.setattr(reconcile_module.Positions, "upsert_one", _FakePositionsUpsert.upsert_one)
    _FakePositionsUpsert.recorded.clear()
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

    data, pk = _FakePositionsUpsert.recorded[0]
    assert data["cost_price"] == 0.764


# ─────────────── 读路径: WS 序列化 ───────────────


def test_position_to_out_dict_rounds_cost_price_by_scale_2(monkeypatch):
    """Given: DB cost_price=1.41914 (若未 round 的中间态), scale=2
    When:  _position_to_out_dict 序列化 (WS position_update)
    Then:  cost_price == 1.42
    """
    monkeypatch.setattr("server.services.push.helpers.get_stock_scale", _fake_scale)
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
    assert out["cost_price"] == 1.42


def test_position_to_out_dict_rounds_cost_price_by_scale_3(monkeypatch):
    """Given: DB cost_price=0.763661 (6 位), scale=3 (ETF)
    Then:  cost_price == 0.764
    """
    monkeypatch.setattr("server.services.push.helpers.get_stock_scale", _fake_scale)
    row = _FakeRow(
        stock_code="000001",
        stock_name="",
        last_vol=100,
        avl_vol=100,
        vol=100,
        cost_price=0.763661,
        synced_at="2026-08-12 10:00:00",
        synced_from="pos_push",
    )
    out = _position_to_out_dict(row)
    assert out["cost_price"] == 0.764
