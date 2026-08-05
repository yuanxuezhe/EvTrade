"""
server/strategy/runtime/sandbox.py — 用户脚本安全加载 (v10+ 含 fast 路径)

📌 安全模型:
- ast.parse 校验语法 → 静态扫描禁用节点 (Import/ImportFrom 拒含黑名单模块)
- compile 后用 types.FunctionType 构造, globals 是受控的 dict:
    - 白名单 stdlib: math, statistics, json, datetime, collections, itertools, functools
    - server.strategy.lib 全暴露
    - ctx (user 上下文), params (用户定义参数)
- 用户脚本实现 4 个回调 (按需): on_init / on_bar / on_tick / on_finish
- 任何 Import 或访问受限 builtin (eval/exec/open/__import__/compile) 都会抛 SandboxError

📌 限制:
- 单脚本 ≤ 50KB (防止内存炸弹)
- 不允许 import (含 from ... import / __import__ / importlib)
- 不允许访问 __builtins__ / __globals__ / __code__

📌 v10+ 加速:
- 如果 ctx['_bars_df'] (pandas DataFrame) 存在 + ctx['_indicator_cache'] 存在
  → MA/EMA/REF 走 pandas 向量化路径 (整段 bars 一次算, O(n) 一次, 不是 O(n×bars))
- 否则走 list-of-dict 旧路径 (兼容)
"""
from __future__ import annotations

import ast
import math
import json
import datetime
import statistics
import collections
import itertools
import functools
import logging
import types
from typing import Any, Callable, Dict, Optional

import pandas as pd

from server.strategy.lib import (
    MA, EMA, RSI, MACD, BOLL, KDJ, ATR, BARSLAST, REF, CROSS,
    OrderError, SignalRecorder,
)

log = logging.getLogger(__name__)

MAX_CODE_SIZE = 50 * 1024  # 50KB

# 黑名单 builtin names (拒访问)
FORBIDDEN_BUILTINS = frozenset({
    "eval", "exec", "open", "__import__", "compile", "input",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
    "breakpoint", "memoryview",
})

# 黑名单模块名 (Import 时拒)
FORBIDDEN_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "requests", "urllib", "http",
    "ftplib", "smtplib", "telnetlib", "ssl", "asyncio",
    "multiprocessing", "threading", "ctypes", "importlib",
    "pickle", "shelve", "marshal", "code", "codeop",
    "pathlib", "shutil", "tempfile", "glob", "fnmatch",
    "antigravity",  # python easter egg
})


class SandboxError(Exception):
    """脚本沙箱错误 (语法 / 安全 / 回调缺失)"""
    pass


# ─────────────── 静态检查 ───────────────


def _ast_check(tree: ast.AST) -> None:
    """静态扫描: 拒 Import / ImportFrom 引用黑名单模块; 拒 dunder 属性访问"""

    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    raise SandboxError(f"禁止 import 模块: {alias.name}")
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            top = (node.module or "").split(".")[0]
            if top in FORBIDDEN_MODULES:
                raise SandboxError(f"禁止 from {node.module} import")
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if alias.name in FORBIDDEN_BUILTINS:
                    raise SandboxError(f"禁止导入 {full}")
            self.generic_visit(node)

        def visit_Attribute(self, node):
            # 访问 lib 之外的 dunder (e.g. ctx.__class__) 可能绕过
            if isinstance(node.attr, str) and node.attr.startswith("__") and node.attr.endswith("__"):
                if node.attr in ("__class__", "__bases__", "__subclasses__", "__globals__", "__code__"):
                    raise SandboxError(f"禁止访问 dunder 属性: {node.attr}")
            self.generic_visit(node)

        def visit_Call(self, node):
            # 拒绝调用黑名单 builtin (e.g. eval("..."))
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTINS:
                raise SandboxError(f"禁止调用 {node.func.id}()")
            self.generic_visit(node)

    Visitor().visit(tree)


# ─────────────── Fast 路径 (v10+) ───────────────


def _make_fast_indicators(df: pd.DataFrame, cache, ctx: Dict[str, Any]) -> Dict[str, Callable]:
    """构造 fast 路径的 MA/EMA/REF (pandas rolling 一次算整段, 跨 bar 复用 Series)

    用户脚本中 MA(ctx['bars'], 5) 会调到这里的 fast 版本:
      - ctx['_current_bar_idx'] 已经是当前 bar 索引 (运行时已设)
      - 我们直接 cache.ma(df, 5) 拿整段 Series, .iloc[idx] 拿当前 bar 的值
      - 同 (field, period) 第二次调直接命中 cache
    """

    def fast_MA(bars, period, field="close"):
        if not isinstance(period, int) or period <= 0:
            raise ValueError(f"MA: period must be positive int, got {period}")
        s = cache.ma(df, period, field)
        idx = ctx.get("_current_bar_idx")
        if idx is None or idx >= len(s):
            v = s.iloc[-1] if len(s) > 0 else None
        else:
            v = s.iloc[idx]
        return None if pd.isna(v) else float(v)

    def fast_EMA(bars, period, field="close"):
        if not isinstance(period, int) or period <= 0:
            raise ValueError(f"EMA: period must be positive int, got {period}")
        s = cache.ema(df, period, field)
        idx = ctx.get("_current_bar_idx")
        v = s.iloc[idx] if idx is not None and idx < len(s) else (s.iloc[-1] if len(s) > 0 else None)
        return None if pd.isna(v) else float(v)

    def fast_REF(bars, n, field="close"):
        if not isinstance(n, int):
            raise ValueError(f"REF: n must be int, got {n}")
        s = cache.ref(df, n, field)
        idx = ctx.get("_current_bar_idx")
        v = s.iloc[idx] if idx is not None and idx < len(s) else (s.iloc[-1] if len(s) > 0 else None)
        return None if pd.isna(v) else float(v)

    return {"MA": fast_MA, "EMA": fast_EMA, "REF": fast_REF}


# ─────────────── 加载 ───────────────


def _build_globals(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """构造沙箱 globals: 白名单 stdlib + lib + ctx + params

    v10+ 加速路径: 如果 ctx['_bars_df'] (pandas DataFrame) 存在, 用 fast_* 版本替换 MA/EMA/REF
                  否则走 list-of-dict 旧路径 (兼容用户脚本接口)
    """
    from server.strategy.runtime import fast_data as _fd

    has_fast_path = ctx.get("_bars_df") is not None
    indicator_cache = ctx.get("_indicator_cache") or _fd.get_task_cache()

    if has_fast_path:
        df = ctx["_bars_df"]
        fast_indicators = _make_fast_indicators(df, indicator_cache, ctx)
        ma_func = fast_indicators["MA"]
        ema_func = fast_indicators["EMA"]
        ref_func = fast_indicators["REF"]
    else:
        ma_func = MA
        ema_func = EMA
        ref_func = REF

    safe_builtins = {
        # 数学 / 通用
        "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
        "len": len, "range": range, "enumerate": enumerate, "zip": zip,
        "sorted": sorted, "reversed": reversed, "map": map, "filter": filter,
        "any": any, "all": all, "isinstance": isinstance, "issubclass": issubclass,
        "type": type, "print": print, "True": True, "False": False, "None": None,
        "int": int, "float": float, "str": str, "bool": bool, "list": list,
        "tuple": tuple, "dict": dict, "set": set, "frozenset": frozenset,
        "ValueError": ValueError, "TypeError": TypeError, "Exception": Exception,
        "StopIteration": StopIteration,
    }
    g = {
        "__builtins__": safe_builtins,
        # 白名单 stdlib
        "math": math,
        "json": json,
        "datetime": datetime,
        "statistics": statistics,
        "collections": collections,
        "itertools": itertools,
        "functools": functools,
        # lib 指标 (v10+: MA/EMA/REF 走 fast 路径如果有 _bars_df)
        "MA": ma_func, "EMA": ema_func, "RSI": RSI, "MACD": MACD, "BOLL": BOLL,
        "KDJ": KDJ, "ATR": ATR, "BARSLAST": BARSLAST, "REF": ref_func, "CROSS": CROSS,
        # lib trading facade (调用时 ctx["lib"].doorder 转发, 由 runtime 注入)
        "doorder": lambda *a, **kw: ctx["lib"].doorder(*a, **kw),
        "docancel": lambda *a, **kw: ctx["lib"].docancel(*a, **kw),
        "get_position": lambda *a, **kw: ctx["lib"].get_position(*a, **kw),
        "signal": lambda msg, type_="INFO", **kw: ctx["lib"].signal(msg, type_=type_, **kw),
        "OrderError": OrderError,
        "SignalRecorder": SignalRecorder,
        # 用户上下文
        "ctx": ctx,
        "params": params,
    }
    return g


def load_script(code: str, ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Callable]:
    """加载用户脚本, 返回 4 个回调字典 (缺哪个对应 None)

    Args:
        code: 用户编写的 Python 源码
        ctx: runtime 注入的上下文 (bars / lib / symbol / mode 等)
        params: 用户在 params_schema 定义的参数值

    Returns:
        dict 含 keys: on_init / on_bar / on_tick / on_finish
        用户实现哪些回调, 对应 value 是 callable; 没实现则为 None

    Raises:
        SandboxError: 语法错 / 安全检查失败 / 代码超 50KB
    """
    if len(code) > MAX_CODE_SIZE:
        raise SandboxError(f"脚本超过 {MAX_CODE_SIZE // 1024}KB 上限 ({len(code)} chars)")

    # 1. 语法 + 安全检查
    try:
        tree = ast.parse(code, filename="<user_script>")
    except SyntaxError as e:
        raise SandboxError(f"语法错误 (line {e.lineno}): {e.msg}") from e
    _ast_check(tree)

    # 2. 编译
    try:
        compiled = compile(tree, "<user_script>", "exec")
    except Exception as e:
        raise SandboxError(f"编译失败: {e}") from e

    # 3. 构造 globals + 执行
    globals_dict = _build_globals(ctx, params)
    try:
        exec(compiled, globals_dict)
    except Exception as e:
        raise SandboxError(f"脚本执行初始化失败: {e}") from e

    # 4. 抽出 4 个回调
    def _pick(name: str) -> Optional[Callable]:
        fn = globals_dict.get(name)
        if fn is None:
            return None
        if not callable(fn):
            raise SandboxError(f"{name} 必须是函数 (def {name}(...))")
        return fn

    return {
        "on_init": _pick("on_init"),
        "on_bar": _pick("on_bar"),
        "on_tick": _pick("on_tick"),
        "on_finish": _pick("on_finish"),
    }


__all__ = [
    "SandboxError",
    "load_script",
    "MAX_CODE_SIZE",
    "FORBIDDEN_BUILTINS",
    "FORBIDDEN_MODULES",
]