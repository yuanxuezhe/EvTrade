"""
test_loader_inject.py — v121+ loader schema 注入测试

覆盖 Phase 2 of change `2026-08-10-strategy-params-sweep-best-live`:
- params_schema 与代码 cls.params 一致 → 覆盖成功, 后续 addstrategy 用 schema 默认值
- params_schema 与代码不一致 → strict fail-fast, ValueError
- params_schema=None → 老行为 (回退到代码自身声明)
- params_schema=[] (空 list) → 拒绝, 防回退误用
- 代码无 params 声明 + schema 给完整 key 集合 → 默认值生效
"""
import os
import sys

# 把 strategy_exec/ 加进 sys.path, 让 import strategy_exec.sandbox.loader 生效
_STRATEGY_EXEC_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'strategy_exec'
)
if _STRATEGY_EXEC_DIR not in sys.path:
    sys.path.insert(0, _STRATEGY_EXEC_DIR)

import pytest

from strategy_exec.sandbox.loader import (
    _extract_declared_keys_from_source,
    _inject_params_from_schema,
    load_strategy_class,
)


# ──── 测试 fixture: 一个合法 ProjectStrategy 父类 (用 bt.Strategy 直替) ────
import backtrader as bt


def _params_to_dict(params) -> dict:
    """统一取 cls.params dict — backtrader AutoInfoClass 用 _getpairs, 普通 tuple 用 dict().
    loader schema 注入后 cls.params 是 tuple, 不注入时是 AutoInfoClass.
    """
    if hasattr(params, "_getpairs"):
        return dict(params._getpairs())
    return dict(params)


# ──── 1. schema 覆盖成功 ────

def test_schema_injects_params_to_class():
    """schema 与代码 params 一致 → cls.params 被 schema 覆盖, 默认值取 schema 的"""
    code = '''
import backtrader as bt

class MAStrategy(bt.Strategy):
    params = (
        ("fast", 5),
        ("slow", 20),
    )
    def next(self):
        pass
'''
    schema = [
        {"key": "fast", "default": 7, "type": "int"},
        {"key": "slow", "default": 30, "type": "int"},
    ]
    cls = load_strategy_class(code, bt.Strategy, params_schema=schema)
    # loader 注入后 cls.params 必须是 backtrader 可实例化的 Params 类
    # (v123 回归: 不能是裸 tuple, 否则 metaclass 实例化时 cls.params() 报
    #  "'tuple' object is not callable")
    assert callable(cls.params)
    params_dict = _params_to_dict(cls.params)
    assert params_dict == {"fast": 7, "slow": 30}
    # 回归: 真实 cerebro.run() 实例化 (走 MetaParams.donew 的 cls.params())
    # 直接 cls() 会因缺 cerebro owner 报 _next_stid, 故用完整 addstrategy + run.
    import pandas as pd
    df = pd.DataFrame(
        {"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
         "close": [1, 2, 3], "volume": [100] * 3, "openinterest": [0] * 3},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(cls, fast=7, slow=30)
    cerebro.run()
    # 实例化参数生效: 用策略实例的参数类断言
    assert dict(cls.params._getpairs()) == {"fast": 7, "slow": 30}


def test_schema_injects_preserves_order():
    """schema 注入后 key 顺序按 schema 顺序 (不是代码原顺序)"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    params = (
        ("slow", 20),
        ("fast", 5),
    )
    def next(self): pass
'''
    schema = [
        {"key": "fast", "default": 7},
        {"key": "slow", "default": 30},
    ]
    cls = load_strategy_class(code, bt.Strategy, params_schema=schema)
    # 注入后按 schema 顺序 (Params 类 _getitems 保持顺序)
    keys = [k for k, _ in cls.params._getitems()]
    assert keys == ["fast", "slow"]  # schema 顺序优先


# ──── 2. strict 模式: code 与 schema 不一致 → ValueError ────

def test_code_params_mismatch_schema_raises_strict():
    """code 多一个 key, schema 没有 → ValueError, 提示哪些 keys 多"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    params = (
        ("fast", 5),
        ("slow", 20),
        ("extra", 99),  # code 多
    )
    def next(self): pass
'''
    schema = [
        {"key": "fast", "default": 5},
        {"key": "slow", "default": 20},
    ]
    with pytest.raises(ValueError, match="strict mode"):
        load_strategy_class(code, bt.Strategy, params_schema=schema)


def test_schema_extra_key_raises_strict():
    """schema 多一个 key, code 没有 → ValueError"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    params = (("fast", 5),)
    def next(self): pass
'''
    schema = [
        {"key": "fast", "default": 5},
        {"key": "missing_in_code", "default": 10},
    ]
    with pytest.raises(ValueError, match="strict mode"):
        load_strategy_class(code, bt.Strategy, params_schema=schema)


# ──── 3. 向后兼容: schema=None → 老行为, 代码 params 生效 ────

def test_backward_compat_no_schema_keeps_old_behavior():
    """schema=None → 不注入, 代码 params 原样生效 (老行为)"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    params = (
        ("fast", 5),
        ("slow", 20),
    )
    def next(self): pass
'''
    cls = load_strategy_class(code, bt.Strategy, params_schema=None)
    # 老行为: backtrader 元类把 params 转成 AutoInfoClass, 用 _getpairs() 取 key-value
    assert _params_to_dict(cls.params) == {"fast": 5, "slow": 20}


def test_default_no_schema_arg_keeps_old_behavior():
    """不传 schema 参 (走默认 None) → 老行为"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    params = (("fast", 5),)
    def next(self): pass
'''
    cls = load_strategy_class(code, bt.Strategy)  # 无 params_schema 参
    assert _params_to_dict(cls.params) == {"fast": 5}


# ──── 4. 代码无 params 声明 + schema 完整 → 默认值注入 ────

def test_code_no_params_with_full_schema_injects_defaults():
    """v121+ 目标场景: 代码无 params tuple, schema 完整 → 注入成功"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
    def next(self): pass
'''
    schema = [
        {"key": "fast", "default": 5, "type": "int"},
        {"key": "slow", "default": 20, "type": "int"},
        {"key": "qty", "default": 100, "type": "int"},
    ]
    cls = load_strategy_class(code, bt.Strategy, params_schema=schema)
    assert _params_to_dict(cls.params) == {"fast": 5, "slow": 20, "qty": 100}


# ──── 5. schema=[] (空 list) → 拒绝注入 (fail-fast 防回退) ────

def test_empty_schema_list_raises():
    """schema=[] (空但非 None) → ValueError, 防止空 schema 静默回退老行为"""
    code = '''
import backtrader as bt
class MAStrategy(bt.Strategy):
    params = (("fast", 5),)
    def next(self): pass
'''
    with pytest.raises(ValueError, match="params_schema 为空"):
        load_strategy_class(code, bt.Strategy, params_schema=[])


# ──── 6. AST helper 单测 ────

def test_extract_declared_keys_basic():
    """_extract_declared_keys_from_source 静态扫 class 体顶层 params 赋值"""
    code = '''
import backtrader as bt
class Foo(bt.Strategy):
    params = (
        ("a", 1),
        ("b", 2),
    )
    def next(self): pass
'''
    assert _extract_declared_keys_from_source(code) == {"a", "b"}


def test_extract_declared_keys_no_params():
    """代码无 params → 空集"""
    code = '''
import backtrader as bt
class Foo(bt.Strategy):
    def next(self): pass
'''
    assert _extract_declared_keys_from_source(code) == set()


def test_extract_declared_keys_list_form():
    """params 也支持 list 形式 (Backtrader 标准)"""
    code = '''
import backtrader as bt
class Foo(bt.Strategy):
    params = [
        ("x", 10),
        ("y", 20),
    ]
'''
    assert _extract_declared_keys_from_source(code) == {"x", "y"}


def test_extract_declared_keys_skips_non_string_first():
    """tuple 元素首项非 string 字面量 → 该 key 跳过 (避免误识别)"""
    code = '''
import backtrader as bt
class Foo(bt.Strategy):
    NUM = 42
    params = (
        ("valid", 1),
    )
'''
    assert _extract_declared_keys_from_source(code) == {"valid"}


# ──── 7. _inject_params_from_schema 直接调用 ────

def test_inject_directly_returns_same_class_with_overridden_params():
    """直接调 _inject_params_from_schema 覆盖已有 cls.params — 覆盖前 schema 需匹配 code"""
    code = '''
import backtrader as bt
class Foo(bt.Strategy):
    params = (("a", 1), ("b", 2),)
    def next(self): pass
'''
    # 先加载
    cls = load_strategy_class(code, bt.Strategy, params_schema=None)
    assert _params_to_dict(cls.params) == {"a": 1, "b": 2}
    # 再注入 (schema 与 code 声明一致 → 成功覆盖默认值)
    schema = [{"key": "a", "default": 99}, {"key": "b", "default": 200}]
    _inject_params_from_schema(cls, code, schema)
    assert _params_to_dict(cls.params) == {"a": 99, "b": 200}
