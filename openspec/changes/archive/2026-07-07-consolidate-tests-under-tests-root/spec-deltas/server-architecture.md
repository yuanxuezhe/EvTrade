# server-architecture delta — consolidate-tests-under-tests-root (新增 REQ-ARCH-006)

> change `2026-07-06-consolidate-tests-under-tests-root`
>
> 既有 REQ-ARCH-001 ~ REQ-ARCH-005 全部保留不变。本 delta 仅**新增** REQ-ARCH-006：测试目录强制约束。

## ADDED Requirements

### REQ-ARCH-006: 测试目录强制约束

The system SHALL 强制所有测试文件位于 `tests/` 根目录下。

#### 目录布局规则

- **测试 = `tests/<area>/<sub>/test_*`**
- `<area>` ∈ `{server, client, hq}`，与生产代码所在根目录一一对应：
  - `server/` → `tests/server/`
  - `client/` → `tests/client/`
  - `hq/` → `tests/hq/`
- **子目录细化**：当生产代码是 `server/services/strategy/<sub>.py`（子包）时，测试 MUST 落在 `tests/server/services/strategy/<sub>/test_*.py`（按子模块细分）
- **不保留** `tests/<area>/<sub>/__init__.py`（与现有 `tests/server/` 平铺风格一致；`tests/` 整体不是 Python 包）

#### 禁止的位置

测试文件 MUST NOT 位于以下位置：

- `server/tests/...`（旧 strategy 子包测试位置，commit `1264bf0` 后的孤儿）
- `client/tests/...`（前端 vitest 测试位置，本次迁到 `tests/client/`）
- `hq/test_*.py`（hq 子项目测试位置，本次迁到 `tests/hq/`）
- 任何其他非 `tests/` 根的目录

#### 测试文件识别模式（CI 检查覆盖）

CI 检查 MUST 匹配以下 glob 模式（同时覆盖 pytest + vitest 两侧）：

- `**/test_*.py`
- `**/*_test.py`
- `**/*.test.js`
- `**/*.spec.js`
- `**/*.test.mjs`
- `**/*.spec.mjs`

#### CI 检查（新增到 `tests/server/test_layer_dependencies.py`）

```python
def test_no_tests_outside_tests_root():
    """REQ-ARCH-006: 所有测试文件 MUST 位于 tests/ 根下.

    Glob 模式覆盖 pytest + vitest 两套测试发现规则.
    """
    import os
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
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
            rel_str = str(path.relative_to(repo_root)).replace(os.sep, "/")
            if not rel_str.startswith("tests/"):
                violations.append(rel_str)
    assert not violations, (
        "REQ-ARCH-006 违规：测试文件不在 tests/ 根下：\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_no_init_py_in_tests_subdirs():
    """REQ-ARCH-006: tests/ 子目录 SHALL NOT 包含 __init__.py.

    避免未来误建 __init__.py 把 tests/ 变成 Python 包.
    """
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    init_files = list((repo_root / "tests").rglob("__init__.py"))
    assert not init_files, (
        "tests/ 子目录不应有 __init__.py: \n"
        + "\n".join(str(p.relative_to(repo_root)) for p in init_files)
    )
```

#### Scenario: 策略测试迁到 tests/server/services/strategy/<sub>/

- **WHEN** 开发者为 `server/services/strategy/regime.py` 写测试
- **THEN** 测试 MUST 在 `tests/server/services/strategy/regime/test_regime.py`
- **AND** NOT 在 `server/tests/strategy/test_regime.py` 或其他位置

#### Scenario: 前端测试迁到 tests/client/

- **WHEN** 开发者为 `client/src/composables/useT0Stats.js` 写测试
- **THEN** 测试 MUST 在 `tests/client/composables/useT0Stats.test.js`
- **AND** NOT 在 `client/tests/composables/useT0Stats.test.js` 或其他位置

#### Scenario: hq 测试迁到 tests/hq/

- **WHEN** hq 子项目新增测试
- **THEN** 测试 MUST 在 `tests/hq/test_<name>.py`
- **AND** NOT 在 `hq/test_<name>.py` 或其他位置

#### Scenario: CI 拦截违规

- **WHEN** 开发者误在 `server/tests/foo/test_foo.py` 新建文件
- **THEN** `pytest tests/server/test_layer_dependencies.py::test_no_tests_outside_tests_root` fail
- **AND** 输出 `REQ-ARCH-006 违规：测试文件不在 tests/ 根下：server/tests/foo/test_foo.py`
- **修复**：用 `git mv` 迁到 `tests/server/<layer>/foo/test_foo.py`

#### Scenario: 误建 __init__.py 被拦截

- **WHEN** 开发者误建 `tests/server/services/strategy/__init__.py`
- **THEN** `pytest tests/server/test_layer_dependencies.py::test_no_init_py_in_tests_subdirs` fail
- **修复**：`rm tests/server/services/strategy/__init__.py`

## 不在范围（与现有 REQ-ARCH-NNN 的关系）

- REQ-ARCH-001 (5 层模块边界)：不变。本 change 只动测试位置，不动生产代码层级
- REQ-ARCH-002 (单向依赖方向)：不变
- REQ-ARCH-003 (文件行数约束)：不变
- REQ-ARCH-004 (统一入口规则)：远程 `2026-07-05-strategy_trade` 已豁免 strategy 子模块 deep import；本 change 不动
- REQ-ARCH-005 (模块依赖图)：不变

## 不在本 change 范围

- ❌ 各 capability 的业务 spec（`trading` / `push` / `data-model` 等）——本次只影响"测试位置"规约本身
- ❌ 测试本身的覆盖率 / 质量提升——本次只迁位置
- ❌ `server/services/strategy/` 子模块 deep import 收敛（远程 `2026-07-05-strategy_trade` 豁免于 REQ-ARCH-004，由后续 PR 处理）
- ❌ `docs/` 静态文档中已归档的 `server/tests/strategy/` 历史引用——保留为历史快照