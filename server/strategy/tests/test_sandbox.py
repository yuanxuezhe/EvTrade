"""
test_sandbox.py — server/strategy/runtime/sandbox.py 单元测试
"""
import pytest

from server.strategy.runtime.sandbox import (
    load_script, SandboxError, MAX_CODE_SIZE,
)


SAMPLE_OK = """
# 简单均线突破策略
def on_init(ctx):
    ctx['state'] = 'idle'

def on_bar(ctx, bar):
    ma5 = MA(ctx['bars'], 5)
    ma20 = MA(ctx['bars'], 20)
    if ma5 and ma20 and ma5 > ma20 and ctx['state'] == 'idle':
        ctx['state'] = 'long'

def on_finish(ctx):
    pass
"""


SAMPLE_IMPORT_OS = """
import os
def on_bar(ctx, bar):
    return os.listdir('/')
"""


SAMPLE_IMPORT_FROM_SUBPROCESS = """
from subprocess import call
def on_bar(ctx, bar):
    call(['ls'])
"""


SAMPLE_EVAL = """
def on_bar(ctx, bar):
    eval('print(1)')
"""


SAMPLE_OPEN = """
def on_bar(ctx, bar):
    open('/etc/passwd').read()
"""


SAMPLE_DUNDER = """
def on_bar(ctx, bar):
    return ctx.__class__
"""


SAMPLE_NO_CALLBACKS = """
x = 1
"""


SAMPLE_SYNTAX = """
def on_bar(ctx, bar):
    return 'unterminated
"""


# ─────────────── 测试 ───────────────


class TestSandbox:
    def test_basic_load(self):
        ctx = {"bars": [], "symbol": "TEST.SH"}
        cbs = load_script(SAMPLE_OK, ctx, params={"x": 1})
        assert cbs["on_init"] is not None
        assert cbs["on_bar"] is not None
        assert cbs["on_finish"] is not None
        assert cbs["on_tick"] is None  # 未实现

    def test_callback_invocation(self):
        """on_bar 能调 MA 指标"""
        ctx = {"bars": [{"close": float(i)} for i in range(30)]}
        cbs = load_script(SAMPLE_OK, ctx, params={})
        cbs["on_init"](ctx)
        bar = {"close": 31.0}
        cbs["on_bar"](ctx, bar)
        assert ctx["state"] == "long"

    def test_forbid_import(self):
        with pytest.raises(SandboxError, match="禁止 import"):
            load_script(SAMPLE_IMPORT_OS, {"bars": []}, {})

    def test_forbid_import_from(self):
        with pytest.raises(SandboxError, match="禁止 from subprocess"):
            load_script(SAMPLE_IMPORT_FROM_SUBPROCESS, {"bars": []}, {})

    def test_forbid_eval(self):
        with pytest.raises(SandboxError, match="禁止调用 eval"):
            load_script(SAMPLE_EVAL, {"bars": []}, {})

    def test_forbid_open(self):
        with pytest.raises(SandboxError, match="禁止调用 open"):
            load_script(SAMPLE_OPEN, {"bars": []}, {})

    def test_forbid_dunder(self):
        with pytest.raises(SandboxError, match="dunder"):
            load_script(SAMPLE_DUNDER, {"bars": []}, {})

    def test_no_callbacks_allowed(self):
        """没回调不报错 (允许只写辅助函数)"""
        cbs = load_script(SAMPLE_NO_CALLBACKS, {}, {})
        assert cbs["on_bar"] is None

    def test_syntax_error(self):
        with pytest.raises(SandboxError, match="语法错误"):
            load_script(SAMPLE_SYNTAX, {}, {})

    def test_size_limit(self):
        big = "# " + ("x" * (MAX_CODE_SIZE + 1))
        with pytest.raises(SandboxError, match="超过"):
            load_script(big, {}, {})

    def test_lib_functions_available(self):
        """MA / EMA / RSI 等可调"""
        code = """
def on_bar(ctx, bar):
    ma = MA(ctx['bars'], 5)
    rsi = RSI(ctx['bars'], 14)
    return ma, rsi
"""
        ctx = {"bars": [{"close": float(i)} for i in range(30)]}
        cbs = load_script(code, ctx, {})
        ma, rsi = cbs["on_bar"](ctx, {"close": 30.0})
        assert ma is not None
        assert rsi is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])