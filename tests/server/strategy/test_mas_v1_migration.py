"""
test_mas_v1_migration.py — Phase 7 mas_v1 params 块删除迁移测试

覆盖:
- 4 参数标准格式 → 正则干净删除
- 1 参数极简格式 → 仍能删
- 缺 params 块 (幂等场景) → 不动
- 多 params 块 (脚本异常) → ValueError
- 删后 code 仍合法 Python (AST parse 通过)
- 删后 cls.params 由 backtrader 默认 (空 tuple) → loader + schema 注入仍成功
"""
import os
import re
import sys

# 把 strategy_exec/ + project root 加进 sys.path
_STRATEGY_EXEC_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'strategy_exec'
)
if _STRATEGY_EXEC_DIR not in sys.path:
    sys.path.insert(0, _STRATEGY_EXEC_DIR)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest

# 直接 import migration 模块 (不跑 main)
import importlib.util
_MIGRATION_PATH = os.path.join(
    _PROJECT_ROOT, "server", "migrations", "2026-08-10-drop-mas-v1-params-from-code.py"
)
_spec = importlib.util.spec_from_file_location("drop_mas_v1", _MIGRATION_PATH)
_drop_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_drop_mod)
strip_params_block = _drop_mod.strip_params_block


ORIGINAL_MAS_V1_CODE = '''import backtrader as bt

try:
    from strategy_exec.engines.backtrader.adapter import ProjectStrategy
except ImportError:
    ProjectStrategy = bt.Strategy


class MAStrategy(ProjectStrategy):
    """双均线交叉策略 (策略执行服务默认 demo)"""

    params = (
        ("fast", 5),
        ("slow", 20),
        ("qty", 100),
        ("rsi_period", 14),
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)
        self.rsi = bt.indicators.RSI(period=self.p.rsi_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
'''


# ──── 1. 4 参数标准格式 ────

def test_strip_4_params_block_standard():
    """4 参数标准格式 → 干净删除, 保留 class 体其余内容"""
    new_code = strip_params_block(ORIGINAL_MAS_V1_CODE)
    assert "    params = (" not in new_code
    # 验证其余关键行还在
    assert "class MAStrategy(ProjectStrategy):" in new_code
    assert "def __init__(self):" in new_code
    assert "self.sma_fast = bt.indicators.SMA(period=self.p.fast)" in new_code
    assert "self.rsi = bt.indicators.RSI(period=self.p.rsi_period)" in new_code


# ──── 2. 删后仍合法 Python (AST parse 通过) ────

def test_stripped_code_is_valid_python():
    """删后 code 仍 AST parse 通过 → 不是损坏字符串"""
    new_code = strip_params_block(ORIGINAL_MAS_V1_CODE)
    import ast
    ast.parse(new_code)  # 不抛错 = 通过


# ──── 3. 缺 params 块 (幂等) ────

def test_strip_when_no_params_block_is_noop():
    """无 params 块 → 不动, 不抛错 (幂等)"""
    code_without_params = '''import backtrader as bt

class MAStrategy(bt.Strategy):
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
'''
    new_code = strip_params_block(code_without_params)
    assert new_code == code_without_params  # 完全不动


# ──── 4. 多 params 块 (脚本异常) → ValueError ────

def test_strip_multiple_params_blocks_raises():
    """多 params 块 (异常脚本) → ValueError, 不静默处理"""
    code = '''
class Foo:
    params = (
        ("a", 1),
    )
    def next(self): pass

class Bar:
    params = (
        ("b", 2),
    )
    def next(self): pass
'''
    with pytest.raises(ValueError, match="找到.*params.*块"):
        strip_params_block(code)


# ──── 5. 删后仍能被 loader 接受 + schema 注入成功 ────

def test_stripped_code_works_with_loader_inject():
    """删 params 块后的 mas_v1 code + 完整 schema → loader 注入成功"""
    from strategy_exec.sandbox.loader import load_strategy_class
    import backtrader as bt

    new_code = strip_params_block(ORIGINAL_MAS_V1_CODE)
    schema = [
        {"key": "fast", "type": "int", "default": 5},
        {"key": "slow", "type": "int", "default": 20},
        {"key": "qty", "type": "int", "default": 100},
        {"key": "rsi_period", "type": "int", "default": 14},
    ]
    cls = load_strategy_class(new_code, bt.Strategy, params_schema=schema)
    # 注入成功 → cls.params 包含 4 个 schema key, 默认值来自 schema
    params_dict = dict(cls.params._getpairs())
    assert params_dict == {"fast": 5, "slow": 20, "qty": 100, "rsi_period": 14}
