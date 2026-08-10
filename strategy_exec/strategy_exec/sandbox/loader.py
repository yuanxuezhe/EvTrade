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
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Type

from backtrader.metabase import AutoInfoClass
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
    params_schema: Optional[List[Dict[str, Any]]] = None,
) -> Type:
    """加载用户脚本, 返用户定义的 bt.Strategy 子类

    Args:
        code: 用户脚本源码 (字符串)
        project_strategy_cls: 项目基类 (ProjectStrategy)
        expected_class_name: 期望类名 (默认: 找第一个 bt.Strategy 子类)
        params_schema: 参数 schema (v121+, list[dict], 每个含 key/type/default/...).
            None = 老行为, 不注入, 依赖代码里 cls.params = (...) 声明.
            非空 = strict fail-fast: 用 schema 覆盖 cls.params, 代码声明必须一致.

    Returns:
        用户定义的策略类 (Type[bt.Strategy])

    Raises:
        SandboxViolationError: import 黑名单/未授权
        ValueError: 用户脚本未定义 bt.Strategy 子类 / AST 语法错 / schema 不一致
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
    else:
        # 默认: 找第一个 ProjectStrategy 子类
        cls = None
        for obj in ns.globals_dict.values():
            if isinstance(obj, type) and issubclass(obj, project_strategy_cls) and obj is not project_strategy_cls:
                cls = obj
                break
        if cls is None:
            raise ValueError("用户脚本未定义任何 ProjectStrategy 子类")

    # ──── 5. (v121+) schema 注入: schema 是唯一契约, 覆盖 cls.params ────
    if params_schema is not None:
        cls = _inject_params_from_schema(cls, code, params_schema)

    return cls


# ──── Schema 注入 helpers (v121+, 2026-08-10) ────
# 决策: schema 是 params 的唯一真源, 代码里不应再写 params = (...).
# loader 拿 schema 后覆盖 cls.params — 必须保持为 backtrader 可实例化的
# Params 类 (AutoInfoClass 派生, callable), 实例化时 metabase.donew 执行
# cls.params() 取值装到 self.p. 不能换成裸 tuple (会报 not callable).
# strict 模式: code 声明的 keys 与 schema 不一致 → 直接 ValueError (fail-fast).


def _extract_declared_keys_from_source(code: str) -> Set[str]:
    """AST 扫用户脚本源码, 提取顶层 class 定义中 `params = (("k", default), ...)` 的 key 集合.

    静态扫 (不实例化类), 只识别 class 体里直接赋值的 `params` tuple.
    支持 nested tuple / list 形式 (Backtrader 标准).
    不支持的写法 (罕见) → 该 keys 当空集, 由 inject 函数按需校验.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()  # 语法错让上层报
    keys: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            # 只识别 class 体顶层 `params = (...)` 赋值
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                tgt = stmt.targets[0]
                if isinstance(tgt, ast.Name) and tgt.id == "params":
                    keys.update(_parse_params_tuple(stmt.value))
                    break  # 一个 class 一个 params, 找到就停
    return keys


def _parse_params_tuple(node: ast.AST) -> Set[str]:
    """ast 节点 (Tuple/List) → key 集合. 元素必须是 (str, Any) tuple."""
    if not isinstance(node, (ast.Tuple, ast.List)):
        return set()
    out: Set[str] = set()
    for elt in node.elts:
        if isinstance(elt, (ast.Tuple, ast.List)) and elt.elts:
            first = elt.elts[0]
            # 只接受 string 字面量 (避免误识别数字/变量)
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                out.add(first.value)
    return out


def _inject_params_from_schema(
    cls: Type,
    code: str,
    params_schema: List[Dict[str, Any]],
) -> Type:
    """以 schema 为准, 覆盖 cls.params (strict fail-fast).

    Args:
        cls: 用户策略类 (ProjectStrategy 子类, 已 exec 加载)
        code: 用户脚本源码 (供 AST 扫 code 声明的 keys)
        params_schema: list of dict, each 含 'key' 字段

    Returns:
        同一个 cls (params 已被覆盖, backtrader 元类下次会读到新值)

    Raises:
        ValueError: schema 空 / schema key 与 code 声明不一致
    """
    if not params_schema:
        raise ValueError(
            "params_schema 为空但 loader 收到非 None — 拒绝注入, "
            "防止回退到老行为. 请确认 script_row.params_schema 正确写入."
        )

    schema_keys = {p["key"] for p in params_schema if isinstance(p, dict) and "key" in p}
    if not schema_keys:
        raise ValueError("params_schema 全无有效 'key' 字段")

    declared = _extract_declared_keys_from_source(code)

    if declared and declared != schema_keys:
        # 只有当代码里实际声明了 params 才走 strict 比较.
        # v121+ 目标态: 代码无 params tuple, schema 是唯一真源 → allowed (declared = ∅).
        only_code = declared - schema_keys
        only_schema = schema_keys - declared
        raise ValueError(
            f"策略类声明的 params 与 schema 不一致 (strict mode):\n"
            f"  code 多出: {sorted(only_code) or '(无)'}\n"
            f"  schema 多出: {sorted(only_schema) or '(无)'}\n"
            f"  v121+: schema 是唯一契约, 请同步代码里的 params = (...) 或调整 schema"
        )

    # 覆盖 cls.params — 必须保持为 backtrader 可实例化的 Params 类!
    # 不能换成裸 tuple: metaclass 实例化时 metabase.donew 会执行 cls.params()
    # (AutoInfoClass 派生类可调用), 裸 tuple 会报 "'tuple' object is not callable".
    # 正确做法: 从 AutoInfoClass 空基 _derive 出新派生类, 保持 schema key 顺序
    # (若用继承的 cls.params 当基, _derive 会保留代码声明的原顺序).
    newparams = OrderedDict((p["key"], p["default"]) for p in params_schema)
    cls.params = AutoInfoClass._derive(cls.__name__, newparams, [])
    log.debug("[loader.inject] %s.params 已被 schema 覆盖: %s",
              cls.__name__, sorted(schema_keys))
    return cls


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