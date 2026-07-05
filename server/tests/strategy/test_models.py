"""
test_models.py — Strategy 4 张 ORM 单测

覆盖：
- 4 张表可正常 create_all（无 schema 错误）
- Strategy 含 type 字段，默认值 'general'
- Strategy 含 ix_strategy_type 索引
- cascade delete：删 Strategy → Regime/Grid/Audit 全部级联
- JSON 字段 round-trip：set_required_flags(['ma_bullish']) → get_required_flags() == ['ma_bullish']
"""
import json
import pytest


def test_strategy_table_exists_and_has_type():
    """Strategy 表注册成功，含 type 字段"""
    from server.services.strategy.models import Strategy
    assert Strategy.__tablename__ == "strategy"
    assert hasattr(Strategy, "type")
    # type 字段默认值
    assert Strategy.type.default.arg == "general"


def test_strategy_has_type_index():
    """Strategy 表必须含 ix_strategy_type 索引（REQ-STRAT-001）"""
    from server.services.strategy.models import Strategy
    index_names = {idx.name for idx in Strategy.__table__.indexes}
    assert "ix_strategy_type" in index_names


def test_order_has_user_def_index():
    """Order 表必须含 ix_orders_user_def 索引（REQ-STRAT-010）"""
    from server.models.orm import Order
    index_names = {idx.name for idx in Order.__table__.indexes}
    assert "ix_orders_user_def" in index_names


def test_strategy_relationships_and_cascade():
    """Strategy ↔ Regime ↔ Grid 三层 relationship + cascade 配置正确"""
    from server.services.strategy.models import Strategy, StrategyRegime, StrategyGrid
    s_rel = Strategy.__mapper__.relationships
    assert "regimes" in s_rel
    # SQLAlchemy 1.4 CascadeOptions 用 save-update / delete / delete-orphan 等字符串属性
    assert "delete-orphan" in s_rel["regimes"].cascade
    assert s_rel["regimes"].passive_deletes is True
    r_rel = StrategyRegime.__mapper__.relationships
    assert "grids" in r_rel
    assert "delete-orphan" in r_rel["grids"].cascade
    assert r_rel["grids"].passive_deletes is True


def test_regime_json_roundtrip():
    """Regime.required_flags / exclude_flags set/get round-trip 一致"""
    from server.services.strategy.models import StrategyRegime
    r = StrategyRegime(name="test", strategy_id=1)
    # 默认空
    assert r.get_required_flags() == []
    assert r.get_exclude_flags() == []
    # 设置中文 flag（ensure_ascii=False 验证）
    r.set_required_flags(["ma_bullish", "macd金叉"])
    assert r.get_required_flags() == ["ma_bullish", "macd金叉"]
    assert "macd金叉" in r.required_flags  # 不被 ASCII escape
    # 清空
    r.set_exclude_flags([])
    assert r.get_exclude_flags() == []


def test_audit_json_roundtrip_and_order_no_optional():
    """Audit.flags_active + action_payload round-trip，order_no 可空"""
    from server.services.strategy.models import StrategyAudit
    a = StrategyAudit(strategy_id=1, trd_date="20260705", trigger_type="grid_buy")
    a.set_flags_active(["ma_bullish"])
    assert a.get_flags_active() == ["ma_bullish"]
    # action_payload None
    a.set_action_payload(None)
    assert a.action_payload is None
    # action_payload dict
    a.set_action_payload({"order_type": "23", "volume": 100, "price": 12.34})
    loaded = a.get_action_payload()
    assert loaded["volume"] == 100
    assert loaded["price"] == 12.34
    # order_no 可空（拒触发场景）
    assert a.order_no is None