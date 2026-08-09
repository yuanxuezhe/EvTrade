# Tasks — consolidate-tests-under-tests-root

共 4 阶段 / ~30 步。每阶段完成后跑对应验证命令。

## Phase 1: Python 测试迁移（server strategy + hq）（~15 步）

- [x] 1. 在 `tests/server/services/strategy/` 下创建 9 个子目录：`models/ repository/ indicators/ flags/ regime/ grid/ engine/ quote_consumer/ api/`
- [x] 2. `git mv server/tests/strategy/test_models.py tests/server/services/strategy/models/test_strategy_models.py` ← 重命名为 `test_strategy_models.py` 避免与 `tests/server/models/test_models.py` 同名碰撞
- [x] 3. `git mv server/tests/strategy/test_repository.py tests/server/services/strategy/repository/test_repository.py`
- [x] 4. `git mv server/tests/strategy/test_indicators.py tests/server/services/strategy/indicators/test_indicators.py`
- [x] 5. `git mv server/tests/strategy/test_flags.py tests/server/services/strategy/flags/test_flags.py`
- [x] 6. `git mv server/tests/strategy/test_regime.py tests/server/services/strategy/regime/test_regime.py`
- [x] 7. `git mv server/tests/strategy/test_grid.py tests/server/services/strategy/grid/test_grid.py`
- [x] 8. `git mv server/tests/strategy/test_engine.py tests/server/services/strategy/engine/test_engine.py`
- [x] 9. `git mv server/tests/strategy/test_quote_consumer.py tests/server/services/strategy/quote_consumer/test_quote_consumer.py`
- [x] 10. `git mv server/tests/strategy/test_api.py tests/server/services/strategy/api/test_api.py`
- [x] 11. `git mv server/tests/strategy/test_t0_endpoint_migration.py tests/server/services/strategy/api/test_t0_endpoint_migration.py`
- [x] 12. 删除 `server/tests/` 整个目录（含 `__pycache__/`，已 gitignored）
- [x] 13. `git mv hq/test_hqserver.py tests/hq/test_hqserver.py`
- [x] 14. 验证：`pytest tests/server/services/strategy/ -v` → **133 passed, 0 failed** ✓（其余 60 failed 是预先存在的 rpc/api/services/push 依赖问题，与本次迁移无关）
- [x] 15. 验证：`ls server/tests/ 2>&1` → No such file or directory ✓

## Phase 2: 前端测试迁移（client → tests/client）（~6 步）

- [x] 16. `git mv client/tests tests/client`（整目录平移，内部结构与相对导入不变）
- [x] 17. 创建 `tests/client/vitest.config.js`：从 `client/vitest.config.js` 内容复制，但：
      - `include`：`'../tests/client/**/*.{test,spec}.{js,mjs}'`
      - `environmentMatchGlobs`：3 条 `../tests/client/{views,components,smoke}/**` → `jsdom`
      - `@` alias：`fileURLToPath(new URL('../../client/src', import.meta.url))`
- [x] 18. 删除 `client/vitest.config.js`
- [x] 19. 修改 `client/package.json` 的 `scripts`：
      - `"test": "vitest run --config ../tests/client/vitest.config.js"`
      - `"test:watch": "vitest --config ../tests/client/vitest.config.js"`
- [x] 20. 验证：`cd client && npm test` → 23/24 suites, 323/324 tests pass（1 failure: HistoryOrders 时区断言，预存 bug，与本次迁移无关；详见"实施发现"）
- [x] 21. 验证：`ls client/tests/ 2>&1` → No such file or directory

## Phase 3: pytest 配置 + conftest 注释（~3 步）

- [x] 22. 修改 `pytest.ini`：`testpaths = hq` → `testpaths = tests`，并加 `addopts = --ignore=tests/server/rpc`（实施时发现 rpc 测试需要真实 broker，否则 testpath 扩展会暴露）
- [x] 23. 修改 `conftest.py` 第 24 行注释：`python -m pytest server/ -v` → `pytest tests/`
- [x] 24. 验证：`pytest tests/ -v` → 380 passed, 54 failed, 11 errors — strategy 部分 133 passed 全绿；其余失败均为预存 bug（api/repo/services push 等），不在本次迁移范围

## Phase 4: CI 锚点（新增 REQ-ARCH-006 检查）（~6 步）

- [x] 25. 在 `tests/server/test_layer_dependencies.py` 中新增 `test_no_tests_outside_tests_root`：
      - 遍历整个仓库（排除 `node_modules/` / `__pycache__/` / `.vite-cache/` / `.pytest_cache/` / `.git/`）
      - glob 模式：`**/test_*.py`、`**/*_test.py`、`**/*.test.{js,mjs}`、`**/*.spec.{js,mjs}`
      - 断言：所有匹配路径都 MUST 以 `tests/` 开头
      - 失败信息：列出违规文件 + 建议迁到的位置
- [x] 26. 验证：`pytest tests/server/test_layer_dependencies.py -v` → 6 passed
- [x] 27. 在 `tests/server/test_layer_dependencies.py` 的同一检查里，对 `tests/<area>/<sub>/__init__.py` 也做反向断言（避免未来误建）：
      - 断言 `tests/server/services/strategy/**/__init__.py` 不存在
      - 实施时发现并清理 `tests/server/api/asset/__init__.py`（空文件，迁移遗留），删除后断言通过
- [x] 28. 验证：故意在某处建 `tests/server/services/strategy/__init__.py`，跑 step 25 的检查，应 fail；删除后通过
- [x] 29. `pytest tests/server/test_layer_dependencies.py tests/server/services/strategy/ -v` → 139 passed（6 layer tests + 133 strategy tests）— 迁移目标全绿
- [x] 30. `cd client && npm test` → 23/24 suites pass（fail: HistoryOrders 时区断言；详见"实施发现"）

## 阶段验收

- Phase 1 完成 → server Python 测试全在 `tests/server/`，hq 测试在 `tests/hq/`
- Phase 2 完成 → client 前端测试全在 `tests/client/`，`npm test` 仍可用
- Phase 3 完成 → `pytest tests/` 命令收敛所有 Python 测试
- Phase 4 完成 → 强制约束有 CI 锚点，违规自动 fail

## 实施发现（建议存档阶段同步到 proposal.md / design.md）

1. **`tests/client/stores/holdings_idb.test.js`** 有 4 处 `../../src/...` 路径 import，依赖旧 `client/tests/` 布局的相对深度。迁到 `tests/client/stores/` 后该相对路径解析为不存在的 `tests/src/...`。**修复**：改用 `@/...` vitest alias（已在 vitest.config.js 配置 `@` → `client/src`），与同文件 line 20 已有的 `vi.mock('@/utils/idb')` 风格一致。这是设计 §3 漏掉的非 `setup-view` 路径情形。
2. **`pytest.ini` 扩展 testpaths 暴露 `tests/server/rpc/test_rpc.py`**：该文件是直连真实 RabbitMQ 的端到端集成脚本，模块加载即 `run_until_complete()`，无 broker 环境必超时失败（30s）。**修复**：加 `addopts = --ignore=tests/server/rpc`（English 注释；Chinese 字符会让 Windows GBK codec 解析 pytest.ini 时炸 UnicodeDecodeError）。
3. **`tests/server/api/asset/__init__.py`**（空文件，迁移遗留）违反 REQ-ARCH-006 的 "测试目录无 `__init__.py`" 约束。**修复**：直接删除（`__init__.py` 内的 `test_adjust.py` 用的是 `server.api.asset` production 路径而非 `tests.server.api.asset`，不受影响）。
4. **`tests/client/views/HistoryOrders.test.js` line 79** 失败：`opts.endDate < new Date().toISOString().slice(0, 10).replace(/-/g, '')`（UTC） 与组件用本地时区 `todayYYYYMMDD()` 在跨本地午夜时分歧。这是与本次迁移无关的预存 flaky bug，建议后续 PR 修。

## 后续（不在本 change）

- 各 capability spec 增量（`server-architecture` / `view-testing-stack` / `frontend` / `quotes` / `strategy`）由 `opsx:archive` 阶段统一合并到 `openspec/specs/<cap>/spec.md`
- `server/services/strategy/` 子模块 deep import 收敛（远程 `2026-07-05-strategy_trade` 豁免于 REQ-ARCH-004，由后续 PR 处理）