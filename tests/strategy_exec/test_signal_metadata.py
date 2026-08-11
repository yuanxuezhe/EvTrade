"""
test_signal_metadata.py — Signal 字段默认值 + payload 序列化/反序列化 (v126, C3)

覆盖:
- Signal 默认值: parent_task_id=None, strategy_name="" (旧 signal 不破坏)
- to_payload: 新字段出现在 dict 中
- payload_to_signal: 缺字段不抛错 (回测/旧 live 兼容)
- payload_to_signal: parent_task_id=int + strategy_name=str 完整反序列化
"""
from strategy_exec.signal.types import Signal, SignalType, payload_to_signal


def _base_signal(**overrides) -> Signal:
    defaults = dict(
        task_id=42, user_id=7, script_id="x",
        signal_type=SignalType.BUY, stock_code="600519.SH",
        price=100.0, volume=100,
    )
    defaults.update(overrides)
    return Signal(**defaults)


def test_signal_default_fields():
    """默认 parent_task_id=None + strategy_name='' (旧 signal 兼容)."""
    s = _base_signal()
    assert s.parent_task_id is None
    assert s.strategy_name == ""


def test_signal_to_payload_includes_metadata():
    """to_payload 输出含 parent_task_id + strategy_name."""
    s = _base_signal(parent_task_id=99, strategy_name="均线策略")
    p = s.to_payload()
    assert p["parent_task_id"] == 99
    assert p["strategy_name"] == "均线策略"


def test_payload_to_signal_missing_fields_defaults():
    """缺新字段的 payload → 默认值 (None / ''), 不抛错."""
    payload = {
        "task_id": 42, "user_id": 7, "script_id": "x",
        "signal_type": "BUY", "stock_code": "600519.SH",
        "price": 100.0, "volume": 100,
    }
    s = payload_to_signal(payload)
    assert s.parent_task_id is None
    assert s.strategy_name == ""


def test_payload_to_signal_with_metadata():
    """含 parent_task_id + strategy_name 的 payload 完整反序列化."""
    payload = {
        "task_id": 42, "user_id": 7, "script_id": "x",
        "signal_type": "BUY", "stock_code": "600519.SH",
        "price": 100.0, "volume": 100,
        "parent_task_id": 1001, "strategy_name": "均线策略",
    }
    s = payload_to_signal(payload)
    assert s.parent_task_id == 1001
    assert s.strategy_name == "均线策略"


def test_payload_to_signal_explicit_none_parent():
    """parent_task_id=null 显式 → None."""
    payload = {
        "task_id": 42, "user_id": 7, "script_id": "x",
        "signal_type": "BUY", "stock_code": "600519.SH",
        "price": 100.0, "volume": 100,
        "parent_task_id": None, "strategy_name": "",
    }
    s = payload_to_signal(payload)
    assert s.parent_task_id is None
    assert s.strategy_name == ""
