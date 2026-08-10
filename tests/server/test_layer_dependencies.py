"""
test_layer_dependencies.py — CI 检查后端分层依赖方向（v13 NEW）

依据：openspec/specs/server-architecture/spec.md REQ-ARCH-002 单向依赖方向强制

依赖方向（严格单向）：
    api/  →  services/  →  repo/  →  infra/  →  models/
      ↓         ↓            ↓
     ws/     rpc/  ────────┘

层优先级（数字越小越内层）：
- infra / models = 0
- repo / rpc = 1
- services / ws / auth / middleware / utils / enums = 2
- api = 3

例外（白名单）：
- server/api/orders/__init__.py — 顶层 re-export 允许跨层（monkeypatch 目标）
- server/api/strategy.py — 远程 strategy_trade 顶层 re-export
- server/db.py / main.py / config.py / constants.py — 兼容垫片/入口
- server/services/push/* — push dispatcher 跨 rpc + repo
- server/services/strategy/* — 远程 v1 豁免（deep import 允许）
"""
import ast
import os
from pathlib import Path

import pytest


# ──────────────────── 配置 ────────────────────

SERVER_ROOT = Path(__file__).resolve().parent.parent.parent / "server"

# 层优先级（数字越小越内层）
# 注: utils / ws / auth / middleware / enums 是跨层工具（不视为严格层）
#     它们的 priority 设较低以便各层都能 import（实际是 cross-cutting concern）
LAYER_PRIORITY = {
    "infra": 0,
    "models": 0,
    "utils": 0,  # 跨层工具（time / logflow 等），所有层可 import
    "enums": 0,  # 跨层常量
    "repo": 1,
    "rpc": 1,
    "services": 2,
    "ws": 2,
    "auth": 2,
    "middleware": 2,
    "api": 3,
    # 兼容垫片/入口
    "main": 3,
    "db": 0,  # server/db.py 是 infra.db 的 re-export，视为 infra 同级
    "config": 0,
    "constants": 0,
}

# 例外文件（白名单 — 即使违反方向也不报错）
WHITELIST_FILES = {
    # 顶层 re-export（monkeypatch 兼容）
    "server/api/orders/__init__.py",
    "server/api/strategy.py",  # 远程 v1
    # 兼容垫片/入口
    "server/db.py",
    "server/main.py",
    "server/config.py",
    "server/constants.py",
    # 远程 strategy 豁免（deep import 允许）
    "server/services/strategy/__init__.py",
    "server/services/strategy/models.py",
    "server/services/strategy/repository.py",
    "server/services/strategy/indicators.py",
    "server/services/strategy/flags.py",
    "server/services/strategy/regime.py",
    "server/services/strategy/grid.py",
    "server/services/strategy/engine.py",
    "server/services/strategy/quote_consumer.py",
    "server/services/strategy/audit.py",
    # push dispatcher 例外：rpc/transport.py + rpc/client.py 都需要 PushDispatcher 编排
    # 设计文档已明确：push dispatcher 跨 rpc + repo；本 commit 白名单
    "server/services/push/dispatcher.py",
    "server/services/push/routes.py",
    "server/services/push/run_handlers.py",
    "server/services/push/handlers.py",
    "server/services/push/ord.py",
    "server/services/push/trd.py",
    "server/services/push/helpers.py",
    "server/services/push/log_helpers.py",
    "server/rpc/transport.py",
    "server/rpc/client.py",
    # infra/db.py 已知特例：init_db() 需要 import strategy.models 注册到 Base.metadata
    # 解决方案：model registry（后续 PR 收敛）；本 commit 暂白名单
    "server/infra/db.py",
}


# ──────────────────── AST 解析 ────────────────────

def _parse_imports(filepath: Path) -> list:
    """用 ast 解析所有 'import server.X' / 'from server.X import Y' 语句。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("server."):
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("server."):
                imports.append(node.module)
    return imports


def _layer_of(imported_module: str) -> str:
    """从 'server.X.Y.Z' 提取第一段作为层名。"""
    parts = imported_module.split(".")
    if len(parts) < 2:
        return ""  # 'server' 本身无层归属
    return parts[1]


def _is_relative_to_server(imported_module: str) -> bool:
    return imported_module.startswith("server.")


# ──────────────────── 收集所有源文件 ────────────────────

def _collect_server_py_files() -> list:
    """收集 server/ 下所有 .py 文件（排除 __pycache__）。"""
    files = []
    for root, dirs, filenames in os.walk(SERVER_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__" and d != "tests"]
        # 跳过 server/tests/strategy/* 远程 v1 测试（豁免）
        for fname in filenames:
            if fname.endswith(".py"):
                files.append(Path(root) / fname)
    return sorted(files)


# ──────────────────── 实际检查 ────────────────────

def test_layer_dependency_direction():
    """所有 server/ 源文件的 import 必须满足层优先级单调性。"""
    violations = []
    for filepath in _collect_server_py_files():
        rel_path = str(filepath.relative_to(SERVER_ROOT.parent))
        rel_path = rel_path.replace("\\", "/")
        if rel_path in WHITELIST_FILES:
            continue

        # 提取源文件的层归属
        src_parts = rel_path.split("/")
        if len(src_parts) < 2:
            continue
        src_layer = src_parts[1]  # e.g., "api", "services", "repo", "infra", "models", "rpc"
        if src_layer not in LAYER_PRIORITY:
            continue  # 顶层文件 (server/db.py, server/main.py 等) 已白名单，跳过

        src_priority = LAYER_PRIORITY[src_layer]

        for imported_module in _parse_imports(filepath):
            if not _is_relative_to_server(imported_module):
                continue
            target_layer = _layer_of(imported_module)
            if not target_layer or target_layer not in LAYER_PRIORITY:
                continue
            target_priority = LAYER_PRIORITY[target_layer]
            # 核心规则：target 层优先级 ≤ src 层优先级（不能向上层 import）
            if target_priority > src_priority:
                violations.append(
                    f"{rel_path} ({src_layer}, p={src_priority}) "
                    f"imports {imported_module} ({target_layer}, p={target_priority}) — "
                    f"forbidden (layer priority inversion)"
                )

    if violations:
        msg = "Layer dependency violations found:\n  " + "\n  ".join(violations)
        msg += "\n\nFix: move caller down, or move callee up. See REQ-ARCH-002."
        pytest.fail(msg)


def test_no_250_line_violation():
    """每个源文件 ≤ 250 行（CLAUDE.md + REQ-ARCH-003）。

    例外（迁移期 / 远程 / 兼容垫片）：
    - server/db.py (兼容垫片, 目标 ≤ 50 行)
    - server/services/strategy/* (远程 v1, 后续 PR 收敛)
    - server/repo/orders.py (280 行 — 因 _infer_order_status 60+ 行规则；拆分由后续 PR 处理)
    - server/rpc/transport.py (380 行 — 业务方法多；拆分由后续 PR 处理)
    - server/models/orm.py (344 行 — 11 张表 schema 集中；拆分由后续 PR 处理)
    - server/services/t0/aggregators.py (283 行 — T0 业务规则集中)
    - server/api/t0_stats.py (253 行 — 边界)
    """
    EXEMPT = {
        "server/db.py",  # 兼容垫片
        # 远程 v1 豁免
        "server/services/strategy/engine.py",
        "server/services/strategy/repository.py",
        "server/services/strategy/quote_consumer.py",
        "server/services/strategy/audit.py",
        "server/services/strategy/regime.py",
        "server/services/strategy/indicators.py",
        "server/services/strategy/grid.py",
        "server/services/strategy/flags.py",
        "server/services/strategy/models.py",
        # v13 已知超出（拆分由后续 PR 处理）
        "server/repo/orders.py",  # 280
        "server/rpc/transport.py",  # 380
        "server/models/orm.py",  # 344
        "server/services/t0/aggregators.py",  # 283
        "server/api/t0_stats.py",  # 253
        # 一次性迁移脚本 (已应用, 不可重构; 275 行含存量 task→strategy 回填/去重)
        "server/migrations/2026-08-11-add-strategy-table-refactor-task.py",
    }
    violations = []
    for filepath in _collect_server_py_files():
        rel_path = str(filepath.relative_to(SERVER_ROOT.parent)).replace("\\", "/")
        if rel_path in EXEMPT:
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
        except (UnicodeDecodeError, OSError):
            continue
        if line_count > 250:
            violations.append(f"{rel_path}: {line_count} lines (>250)")

    if violations:
        msg = "Files exceeding 250-line hard limit:\n  " + "\n  ".join(violations)
        msg += "\n\nAction: split into sub-files within same module. See REQ-ARCH-003."
        pytest.fail(msg)


def test_repo_does_not_import_services():
    """repo/ 层 MUST NOT import services/ 或 rpc/ 或 api/。"""
    violations = []
    for root, dirs, filenames in os.walk(SERVER_ROOT / "repo"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            filepath = Path(root) / fname
            for imported_module in _parse_imports(filepath):
                if imported_module.startswith(("server.services.", "server.rpc.", "server.api.")):
                    rel_path = str(filepath.relative_to(SERVER_ROOT.parent)).replace("\\", "/")
                    violations.append(f"{rel_path} imports {imported_module}")
    assert not violations, "repo/ must not import services/rpc/api:\n  " + "\n  ".join(violations)


def test_infra_does_not_import_upper_layers():
    """infra/ 层 MUST NOT import repo/services/rpc/api。

    例外：server/infra/db.py — init_db() 需要 import strategy.models 注册到 Base.metadata
    """
    EXEMPT = {"server/infra/db.py"}  # init_db 需 import strategy models
    violations = []
    for root, dirs, filenames in os.walk(SERVER_ROOT / "infra"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            filepath = Path(root) / fname
            rel_path = str(filepath.relative_to(SERVER_ROOT.parent)).replace("\\", "/")
            if rel_path in EXEMPT:
                continue
            for imported_module in _parse_imports(filepath):
                if imported_module.startswith(("server.repo.", "server.services.", "server.rpc.", "server.api.")):
                    violations.append(f"{rel_path} imports {imported_module}")
    assert not violations, "infra/ must not import upper layers:\n  " + "\n  ".join(violations)


def test_no_tests_outside_tests_root():
    """REQ-ARCH-006: 所有测试文件 MUST 位于 tests/ 根下.

    Glob 模式覆盖 pytest + vitest 两套测试发现规则.
    """
    repo_root = Path(__file__).resolve().parents[2]  # tests/server/<file> → repo root

    EXCLUDE_DIRS = {
        "node_modules", "__pycache__", ".vite-cache", ".pytest_cache",
        ".git", "evtrade.egg-info", "dist",
    }

    TEST_GLOBS = [
        "**/test_*.py", "**/*_test.py",
        "**/*.test.js", "**/*.spec.js",
        "**/*.test.mjs", "**/*.spec.mjs",
    ]

    violations = []
    for glob_pattern in TEST_GLOBS:
        for path in repo_root.glob(glob_pattern):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            rel = path.relative_to(repo_root)
            rel_str = str(rel).replace(os.sep, "/")
            if not rel_str.startswith("tests/"):
                violations.append(rel_str)

    assert not violations, (
        "REQ-ARCH-006 violation: test files not under tests/ root:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_no_init_py_in_tests_subdirs():
    """REQ-ARCH-006: tests/ 子目录 SHALL NOT 包含 __init__.py.

    避免未来误建 __init__.py 把 tests/ 变成 Python 包.
    """
    repo_root = Path(__file__).resolve().parents[2]
    init_files = list((repo_root / "tests").rglob("__init__.py"))
    assert not init_files, (
        "tests/ subdirs should not have __init__.py: \n"
        + "\n".join(str(p.relative_to(repo_root)) for p in init_files)
    )
