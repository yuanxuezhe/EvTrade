# Design — consolidate-tests-under-tests-root

本文档说明迁移的**具体技术细节**，作为 `proposal.md` 的补充。读者：实施 `tasks.md` 的工程师。

## 1. 迁移总览

```
迁移前                                迁移后
─────────────────────────────────────────────────────────────────
server/tests/strategy/*.py (10)   →   tests/server/services/strategy/<sub>/*.py
client/tests/**/*.{test,spec}.js →   tests/client/**/*.{test,spec}.js  (整目录平移)
client/tests/setup-view.js        →   tests/client/setup-view.js
client/vitest.config.js           →   tests/client/vitest.config.js (内容改写)
hq/test_hqserver.py               →   tests/hq/test_hqserver.py
                                      ────────────────────
                                      删除:
                                      - server/tests/ (整个目录)
                                      - client/tests/ (整个目录)
                                      - client/vitest.config.js (旧位置)
                                      - hq/test_hqserver.py
```

## 2. Strategy 子模块拆分依据

依据：`server/tests/strategy/test_<name>.py` 的 import 段。逐一对照：

| 测试文件 | 主要 import | 归属子模块 |
|---|---|---|
| `test_models.py` | `server.services.strategy.models` | `models/` |
| `test_repository.py` | `server.services.strategy.repository` | `repository/` |
| `test_indicators.py` | `server.services.strategy.indicators` | `indicators/` |
| `test_flags.py` | `server.services.strategy.flags` | `flags/` |
| `test_regime.py` | `server.services.strategy.regime` | `regime/` |
| `test_grid.py` | `server.services.strategy.grid` | `grid/` |
| `test_engine.py` | `server.services.strategy.engine` | `engine/` |
| `test_quote_consumer.py` | `server.services.strategy.quote_consumer` | `quote_consumer/` |
| `test_api.py` | `server.services.strategy.repository` + `TestClient` + endpoints | `api/` |
| `test_t0_endpoint_migration.py` | 4 个 t0_* 端点（user_def=JOIN migration） | `api/` |

`test_api.py` 与 `test_t0_endpoint_migration.py` 都用 `TestClient`，归 `api/`（与其他 strategy 测试的纯函数性质不同，是端点级测试）。

## 3. 前端相对导入为何不变

`client/tests/` 内文件之间的相对导入是相对**文件所在目录**计算的，与 `client/tests/` 的绝对根位置无关。

```
迁移前                              迁移后
─────────────────────────────────────────────────────────────────
client/tests/views/Trade.test.js      tests/client/views/Trade.test.js
  import '../setup-view'                import '../setup-view'
    → client/tests/setup-view.js         → tests/client/setup-view.js  ✓ 同文件

client/tests/modules/strategy/
  StrategyMonitor.test.js             tests/client/modules/strategy/
  import '../../setup-view'             StrategyMonitor.test.js
    → client/tests/setup-view.js         import '../../setup-view'
                                          → tests/client/setup-view.js  ✓ 同文件
```

12 个测试文件用 `'../setup-view'` 或 `'../../setup-view'`，迁移后**自动保持**，无需改。

唯一会"看起来变"的是文件路径中的 `client/`，但运行时 vitest 只关心文件内容。

## 4. vitest.config.js 改写详解

### 4.1 旧配置（`client/vitest.config.js`）

```js
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),  // → client/src
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['tests/**/*.{test,spec}.{js,mjs}'],  // → client/tests/**
    exclude: ['node_modules', 'dist'],
    environmentMatchGlobs: [
      ['tests/views/**', 'jsdom'],
      ['tests/components/**', 'jsdom'],
      ['tests/smoke/**', 'jsdom'],
    ],
  },
})
```

### 4.2 新配置（`tests/client/vitest.config.js`）

```js
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('../../client/src', import.meta.url)),  // → ../../client/src
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['../tests/client/**/*.{test,spec}.{js,mjs}'],
    exclude: ['node_modules', 'dist'],
    environmentMatchGlobs: [
      ['../tests/client/views/**', 'jsdom'],
      ['../tests/client/components/**', 'jsdom'],
      ['../tests/client/smoke/**', 'jsdom'],
    ],
  },
})
```

### 4.3 关键路径解释

`tests/client/vitest.config.js` 中的相对路径以**该配置文件所在目录**为基准：

| 配置项 | 解析后实际指向 |
|---|---|
| `include: '../tests/client/**'` | `<config-dir>/../tests/client/**` = `tests/client/**` |
| `environmentMatchGlobs: ['../tests/client/views/**', 'jsdom']` | `tests/client/views/**` |
| `alias '@': fileURLToPath(new URL('../../client/src', import.meta.url))` | `client/src/`（从 `tests/client/` 上溯 2 层） |

### 4.4 为什么不把 `@` 改成绝对路径

绝对路径在 Windows / Linux / macOS 下形式不同，会破坏跨平台性。相对 URL（`'../../client/src'`）由 Node `URL` 解析器自动转平台正确路径，是 Vite 官方推荐做法。

## 5. pytest.ini 改写详解

```diff
 [pytest]
 asyncio_mode = auto
-testpaths = hq
+testpaths = tests
```

`testpaths = tests` 让 pytest 默认从 `tests/` 根开始收集（而不是只收集 `hq/`）。**所有** `test_*.py` 在 `tests/` 下都会被自动发现，包括：
- `tests/server/...`（已有 + 新迁 strategy）
- `tests/hq/test_hqserver.py`（新迁）
- 未来新增的 `tests/<area>/...`

## 6. CI 锚点：`test_no_tests_outside_tests_root`

新增到 `tests/server/test_layer_dependencies.py`：

```python
def test_no_tests_outside_tests_root():
    """REQ-ARCH-006: 所有测试文件 MUST 位于 tests/ 根下.

    Glob 模式覆盖 pytest + vitest 两套测试发现规则.
    """
    import os
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]  # tests/server/<file> → repo root

    # 排除目录（与 vitest.exclude + pytest 的 collect_ignore 等价）
    EXCLUDE_DIRS = {
        "node_modules", "__pycache__", ".vite-cache", ".pytest_cache",
        ".git", "evtrade.egg-info", "dist", ".vite-cache",
    }

    # 测试文件识别模式
    TEST_GLOBS = [
        "**/test_*.py", "**/*_test.py",
        "**/*.test.js", "**/*.spec.js",
        "**/*.test.mjs", "**/*.spec.mjs",
        # 注：pytest 不收 .test.js，但 vitest 收；为统一在仓库层面检查，两边都列
    ]

    violations = []
    for glob_pattern in TEST_GLOBS:
        for path in repo_root.glob(glob_pattern):
            # 过滤排除目录
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            rel = path.relative_to(repo_root)
            rel_str = str(rel).replace(os.sep, "/")
            if not rel_str.startswith("tests/"):
                violations.append(rel_str)

    assert not violations, (
        "REQ-ARCH-006 违规：测试文件不在 tests/ 根下：\n"
        + "\n".join(f"  {v}" for v in violations)
    )
```

辅以反向断言：

```python
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

## 7. 风险点（实施注意）

### 7.1 `__pycache__/` 处理

`server/tests/strategy/__pycache__/` 是 Python 自动生成的缓存，**已 gitignored**（`.gitignore`），不需要手动删除。删 `server/tests/` 整个目录时一并清掉即可。

### 7.2 `evtrade.egg-info/` 处理

`evtrade.egg-info/` 是 `setup.py` 安装时自动生成，不在 `server/tests/` 范畴，本次不动。

### 7.3 `conftest.py` 注释清理

```diff
-  - 也不动生产代码（生产代码用 `from server.X` 走限定名）。
-  - 跑测试时仍 `cd D:/workspace/EvTrade && python -m pytest server/ -v`。
+  - 也不动生产代码（生产代码用 `from server.X` 走限定名）。
+  - 跑测试时 `cd F:/EvTrade && pytest tests/`（testpaths = tests 已在 pytest.ini 收敛）。
```

注释改不改**不影响功能**。但保留旧命令会误导读者，所以顺手清理。

### 7.4 git mv vs mv

实施时优先用 `git mv`，保留文件 history（commit `1264bf0` 当年的迁移也是 `git mv`）。如果用纯 `mv`，git 视为"删除 + 新增"，丢失 blame 历史。

### 7.5 提交粒度建议

- commit 1：Phase 1（Python 测试迁移 + pytest.ini + conftest 注释）
- commit 2：Phase 2（前端测试迁移 + vitest.config.js 迁移 + package.json scripts）
- commit 3：Phase 4（CI 锚点）

每个 commit 独立 `pytest tests/ -v` / `cd client && npm test` 通过。

## 8. 与现有规约的协调

- **REQ-ARCH-001 (5 层模块边界)**：不变。strategy 仍在 `services/` 层。
- **REQ-ARCH-002 (单向依赖方向)**：不变。strategy 测试仍只测该层。
- **REQ-ARCH-004 (统一入口规则)**：远程 `2026-07-05-strategy_trade` 已豁免 strategy 子模块 deep import；本 change 不动。
- **REQ-ARCH-003 (文件行数约束)**：不变。
- **本 change 新增 REQ-ARCH-006**：测试目录强制约束。

## 9. 验收清单

实施完成后，逐项确认：

- [ ] `ls server/tests/` → 不存在
- [ ] `ls client/tests/` → 不存在
- [ ] `ls hq/test_hqserver.py` → 不存在
- [ ] `find . -name "test_*.py" -not -path "*/node_modules/*" -not -path "*/__pycache__/*"` → 全在 `tests/` 下
- [ ] `find . -name "*.test.js" -not -path "*/node_modules/*" -not -path "*/__pycache__/*"` → 全在 `tests/` 下
- [ ] `pytest tests/ -v` → 全绿
- [ ] `cd client && npm test` → 全绿
- [ ] `pytest tests/server/test_layer_dependencies.py -v` → 含新加 `test_no_tests_outside_tests_root` 通过
- [ ] `client/package.json` 的 `test` script 含 `--config ../tests/client/vitest.config.js`
- [ ] `pytest.ini` 含 `testpaths = tests`