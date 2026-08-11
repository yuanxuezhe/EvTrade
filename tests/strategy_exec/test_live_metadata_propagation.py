"""
test_live_metadata_propagation.py — LiveRunner 透传 parent_task_id/strategy_name (v126, C8)

覆盖:
- LiveRunner.__init__ 保存 parent_task_id + strategy_name
- _set_task_meta 调用时透传到 adapter (self._parent_task_id / self._strategy_name)
- 默认值 None / "" (旧 sweep live 路径兼容)
- Signal publish payload 含 2 字段
"""
import asyncio
import pytest

from strategy_exec.engines.backtrader.adapter import ProjectStrategy
from strategy_exec.engines.backtrader.live import LiveRunner
from strategy_exec.signal.types import Signal, SignalType


def _make_runner(parent_task_id=None, strategy_name="") -> LiveRunner:
    return LiveRunner(
        task_id=42, user_id=1, script_id="mas_v1", stock_code="600519.SH",
        params={"fast": 5, "slow": 20},
        code="class S(ProjectStrategy): pass\n",
        parent_task_id=parent_task_id,
        strategy_name=strategy_name,
    )


def test_live_runner_stores_metadata():
    """LiveRunner.__init__ 保存 parent_task_id + strategy_name."""
    r = _make_runner(parent_task_id=5555, strategy_name="双均线")
    assert r.parent_task_id == 5555
    assert r.strategy_name == "双均线"


def test_live_runner_default_metadata_none():
    """默认值 None / "" (旧 sweep live 路径兼容, 不传 2 字段)."""
    r = _make_runner()
    assert r.parent_task_id is None
    assert r.strategy_name == ""


def test_set_task_meta_propagates_metadata_to_strategy():
    """_set_task_meta 调 adapter → 内部 _parent_task_id / _strategy_name 写入."""
    r = _make_runner(parent_task_id=7777, strategy_name="均线策略")
    # adapter 暴露 _set_task_meta; 直接调 (不依赖 backtrader 实例化)
    # 使用 ProjectStrategy 基类 fake instance
    fake_strategy = ProjectStrategy.__new__(ProjectStrategy)
    fake_strategy._set_task_meta(
        task_id=r.task_id, user_id=r.user_id, script_id=r.script_id, mode="live",
        parent_task_id=r.parent_task_id, strategy_name=r.strategy_name,
    )
    assert fake_strategy._parent_task_id == 7777
    assert fake_strategy._strategy_name == "均线策略"


def test_signal_payload_contains_metadata():
    """Signal publish 时 parent_task_id + strategy_name 出现在 to_payload."""
    s = Signal(
        task_id=42, user_id=1, script_id="mas_v1",
        signal_type=SignalType.BUY, stock_code="600519.SH",
        price=10.0, volume=100,
        parent_task_id=5555, strategy_name="双均线",
    )
    p = s.to_payload()
    assert p["parent_task_id"] == 5555
    assert p["strategy_name"] == "双均线"


def test_signal_default_metadata_compatible_with_backtest():
    """Signal 默认 None / "" 不污染 backtest 路径 payload."""
    s = Signal(
        task_id=42, user_id=1, script_id="mas_v1",
        signal_type=SignalType.BUY, stock_code="600519.SH",
        price=10.0, volume=100,
    )
    p = s.to_payload()
    assert p["parent_task_id"] is None
    assert p["strategy_name"] == ""


def test_start_live_runner_signature_accepts_metadata():
    """start_live_runner 签名含 parent_task_id + strategy_name (可选)."""
    import inspect
    sig = inspect.signature(
        __import__("strategy_exec.engines.backtrader.live", fromlist=["start_live_runner"]).start_live_runner
    )
    assert "parent_task_id" in sig.parameters
    assert "strategy_name" in sig.parameters
    # 两者都 Optional / 默认值
    assert sig.parameters["parent_task_id"].default is None
    assert sig.parameters["strategy_name"].default == ""