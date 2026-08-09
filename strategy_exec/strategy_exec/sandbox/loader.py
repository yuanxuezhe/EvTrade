"""
strategy_exec.sandbox.loader — 用户 Python 脚本沙箱加载

📌 安全约束:
- 不允许 import: os.system / subprocess / open / socket / requests / urllib / http.client
- 允许 import: backtrader / numpy / pandas / math / json / datetime / typing
- 用户必须定义一个 class, 继承 ProjectStrategy (或 bt.Strategy 基类)
- 用户脚本代码作为字符串传入, exec 在受限 namespace 中

📌 用法:
    cls = load_strategy_class(code_string, project_strategy_cls=ProjectStrategy)
    instance = cls  # Backtrader 后续: cerebro.addstrategy(instance)
"""

from __future__ import annotations

import ast
import builtins
import logging
import sys
import types
import typing
from typing import Any, Optional, Type

from strategy_exec.config import get_settings

log = logging.getLogger(__name__)


class SandboxViolationError(Exception):
    """用户脚本违反沙箱约束"""


class SandboxNamespace:
    """受限命名空间 — 注入用户脚本时使用"""

    def __init__(self, project_strategy_cls: Type) -> None:
        # 允许的内置
        self._builtins = {
            "__builtins__": {
                "__import__": self._safe_import,
                # 用户脚本要定义 class (继承 bt.Strategy/ProjectStrategy),
                # 缺 __build_class__ 时任何 class 语句都会 NameError
                "__build_class__": builtins.__build_class__,
                "object": builtins.object,
                "property": builtins.property,
                "staticmethod": builtins.staticmethod,
                "classmethod": builtins.classmethod,
                "Exception": builtins.Exception,
                "ImportError": builtins.ImportError,
                "RuntimeError": builtins.RuntimeError,
                "NotImplementedError": builtins.NotImplementedError,
                "StopIteration": builtins.StopIteration,
                "KeyboardInterrupt": builtins.KeyboardInterrupt,
                "IndexError": builtins.IndexError,
                "KeyError": builtins.KeyError,
                "ZeroDivisionError": builtins.ZeroDivisionError,
                "OSError": builtins.OSError,
                "LookupError": builtins.LookupError,
                "ArithmeticError": builtins.ArithmeticError,
                "ValueError": builtins.ValueError,
                "TypeError": builtins.TypeError,
                "AttributeError": builtins.AttributeError,
                "getattr": builtins.getattr,
                "setattr": builtins.setattr,
                "hasattr": builtins.hasattr,
                "callable": builtins.callable,
                "iter": builtins.iter,
                "next": builtins.next,
                "hash": builtins.hash,
                "id": builtins.id,
                "super": builtins.super,
                "format": builtins.format,
                "pow": builtins.pow,
                "divmod": builtins.divmod,
                "complex": builtins.complex,
                "ord": builtins.ord,
                "chr": builtins.chr,
                "bytes": builtins.bytes,
                "bytearray": builtins.bytearray,
                "frozenset": builtins.frozenset,
                "slice": builtins.slice,
                "abs": builtins.abs,
                "all": builtins.all,
                "any": builtins.any,
                "bool": builtins.bool,
                "dict": builtins.dict,
                "enumerate": builtins.enumerate,
                "filter": builtins.filter,
                "float": builtins.float,
                "int": builtins.int,
                "isinstance": builtins.isinstance,
                "issubclass": builtins.issubclass,
                "len": builtins.len,
                "list": builtins.list,
                "map": builtins.map,
                "max": builtins.max,
                "min": builtins.min,
                "print": builtins.print,
                "range": builtins.range,
                "repr": builtins.repr,
                "reversed": builtins.reversed,
                "round": builtins.round,
                "set": builtins.set,
                "sorted": builtins.sorted,
                "str": builtins.str,
                "sum": builtins.sum,
                "tuple": builtins.tuple,
                "type": builtins.type,
                "zip": builtins.zip,
            },
        }
        # 允许的模块
        try:
            import backtrader as bt
            self._modules = {"backtrader": bt, "bt": bt}
        except ImportError:
            self._modules = {}
        try:
            import numpy as np
            self._modules["numpy"] = np
            self._modules["np"] = np
        except ImportError:
            pass
        try:
            import pandas as pd
            self._modules["pandas"] = pd
            self._modules["pd"] = pd
        except ImportError:
            pass
        import math, json
        from datetime import datetime, timedelta, timezone
        from typing import Optional, List, Dict, Any, Tuple
        self._modules.update({
            "math": math, "json": json,
            "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
            "typing": typing,
        })
        # 项目基类
        self._modules["ProjectStrategy"] = project_strategy_cls
        # 全局 namespace
        self._globals = dict(self._modules)
        self._globals.update(self._builtins)
        # exec 模块级代码需要这些 dunder (脚本常写 if __name__ == "__main__")
        self._globals.setdefault("__name__", "__sandbox__")
        self._globals.setdefault("__file__", "<sandbox>")
        self._globals.setdefault("__package__", None)
        # 用户脚本定义 class 后其 __module__ 会是 '__sandbox__',
        # Backtrader 元类在 donew() 里执行 sys.modules[cls.__module__],
        # 必须让 sys.modules['__sandbox__'] 指向一个真实 module, 否则 KeyError.
        _sandbox_mod = types.ModuleType("__sandbox__")
        _sandbox_mod.__dict__.update(self._globals)
        sys.modules["__sandbox__"] = _sandbox_mod

    def _safe_import(self, name: str, *args, **kwargs):
        """拦截 __import__: 仅允许白名单模块"""
        top = name.split(".")[0]
        settings = get_settings()
        blocked = settings.blocked_module_list()
        allowed = settings.allowed_module_list()
        # 项目内部受信模块: ProjectStrategy 基类 (用户脚本 try/except 导入它,
        # 沙箱已注入同名 ProjectStrategy, 此处放行以兼容常见脚本写法)
        if name == "strategy_exec.engines.backtrader.adapter":
            return __import__(name, *args, **kwargs)
        if top in blocked:
            raise SandboxViolationError(f"禁止 import '{name}' (blocked module)")
        if top not in allowed and top not in ("backtrader", "bt", "numpy", "np", "pandas", "pd"):
            raise SandboxViolationError(f"未授权 import '{name}' (allowed={allowed})")
        return __import__(name, *args, **kwargs)

    @property
    def globals_dict(self) -> dict:
        """返 namespace dict (exec 用)"""
        return self._globals


def load_strategy_class(
    code: str,
    project_strategy_cls: Type,
    expected_class_name: Optional[str] = None,
) -> Type:
    """加载用户脚本, 返用户定义的 bt.Strategy 子类

    Args:
        code: 用户脚本源码 (字符串)
        project_strategy_cls: 项目基类 (ProjectStrategy)
        expected_class_name: 期望类名 (默认: 找第一个 bt.Strategy 子类)

    Returns:
        用户定义的策略类 (Type[bt.Strategy])

    Raises:
        SandboxViolationError: import 黑名单/未授权
        ValueError: 用户脚本未定义 bt.Strategy 子类 / AST 语法错
    """
    # ──── 1. AST 静态扫描: 检查危险调用 ────
    _static_check(code)

    # ──── 2. 构造受限 namespace ────
    ns = SandboxNamespace(project_strategy_cls)

    # ──── 3. exec 用户代码 ────
    try:
        exec(code, ns.globals_dict)
    except SandboxViolationError:
        raise
    except Exception as e:
        raise ValueError(f"用户脚本执行失败: {e}")

    # ──── 4. 找 bt.Strategy 子类 ────
    if expected_class_name:
        cls = ns.globals_dict.get(expected_class_name)
        if cls is None:
            raise ValueError(f"用户脚本未定义类 '{expected_class_name}'")
        if not isinstance(cls, type) or not issubclass(cls, project_strategy_cls):
            raise ValueError(
                f"类 '{expected_class_name}' 不是 ProjectStrategy 的子类"
            )
        return cls

    # 默认: 找第一个 ProjectStrategy 子类
    for obj in ns.globals_dict.values():
        if isinstance(obj, type) and issubclass(obj, project_strategy_cls) and obj is not project_strategy_cls:
            return obj
    raise ValueError("用户脚本未定义任何 ProjectStrategy 子类")


# ──── 危险调用 AST 检测 ────

_BLOCKED_NAMES = {
    "os.system", "os.popen", "os.execv", "os.execve", "os.execvp",
    "subprocess.run", "subprocess.call", "subprocess.Popen", "subprocess.check_output",
    "socket.socket", "socket.create_connection", "socket.connect",
    "urllib.request.urlopen", "urllib.request.Request",
    "http.client.HTTPConnection",
    "eval", "exec", "compile",  # 嵌套 exec
    "__import__",
}


def _static_check(code: str) -> None:
    """AST 扫描: 静态检查危险调用"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"用户脚本语法错: {e}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = _get_func_name(node.func)
            if func_name in _BLOCKED_NAMES:
                raise SandboxViolationError(
                    f"用户脚本包含禁止调用: {func_name}() "
                    f"(allowed: bt.Strategy/indicators + 计算)"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                settings = get_settings()
                if top in settings.blocked_module_list():
                    raise SandboxViolationError(
                        f"用户脚本禁止 import '{alias.name}'"
                    )


def _get_func_name(node: ast.AST) -> Optional[str]:
    """ast.Call.func → 完整函数名 (含 attribute chain)"""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None