# consolidate-tests-under-tests-root — 测试目录全部上收 tests/

> S 级 / M 工作量。**单一原则**：所有测试文件必须在 `tests/` 根下，其他位置一律清掉。

## Why

当前测试散落在 3 个非 `tests/` 目录，与 `tests/server/<layer>/` 镜像规约不一致，破坏"测试在 tests/"的全局规约：

| 散落位置 | 文件数 | 行数 | 与现有规约的关系 |
|---|---|---|---|
| `server/tests/strategy/*.py` | 10 | 2309 | 远程 `2026-07-05-strategy_trade` 实现 `server/services/strategy/` 时未迁测试，**唯一**绕过 commit `1264bf0 chore(tests): 迁 server/test_*.py → tests/server/ 镜像目录（5 层分组）` 的孤儿 |
| `client/tests/**/*.{test,spec}.js` | 25 + setup-view.js | ~5K+ | 前端 vitest 在 `client/tests/` 自成一系，未走 `tests/` |
| `hq/test_hqserver.py` | 1 | ~17K 行（17KB） | hq 是独立子项目（`pytest.ini testpaths = hq`），但仍属"测试不在 tests/"的违规 |

**与既有规约的接续**：
- commit `1264bf0` 已确立 `tests/server/<layer>/` 镜像规约（5 层分组）
- `openspec/specs/server-architecture/spec.md` 第 10 行已写："测试镜像目录清晰（`tests/server/<layer>/`）"
- 本 change 把规约从"已有约定"升级为 **REQ-ARCH-006 强制约束**，并扩展到 hq / client / strategy 子模块

**原则**：
- 测试 = `tests/<area>/<sub>/test_*`
- `<area>` ∈ `{server, client, hq}`，与生产代码所在根目录一一对应
- 子目录细化颗粒度：strategy 按 `models / repository / indicators / flags / regime / grid / engine / quote_consumer / api` 9 个子模块各建子目录
- **不**保留 `tests/<area>/<sub>/__init__.py`（与现有 `tests/server/` 平铺风格一致）

## What Changes

### 测试位置重映射

**Server — strategy（10 文件 → 9 个子目录）**

| 原位置 | 新位置 |
|---|---|
| `server/tests/strategy/test_models.py` | `tests/server/services/strategy/models/test_models.py` |
| `server/tests/strategy/test_repository.py` | `tests/server/services/strategy/repository/test_repository.py` |
| `server/tests/strategy/test_indicators.py` | `tests/server/services/strategy/indicators/test_indicators.py` |
| `server/tests/strategy/test_flags.py` | `tests/server/services/strategy/flags/test_flags.py` |
| `server/tests/strategy/test_regime.py` | `tests/server/services/strategy/regime/test_regime.py` |
| `server/tests/strategy/test_grid.py` | `tests/server/services/strategy/grid/test_grid.py` |
| `server/tests/strategy/test_engine.py` | `tests/server/services/strategy/engine/test_engine.py` |
| `server/tests/strategy/test_quote_consumer.py` | `tests/server/services/strategy/quote_consumer/test_quote_consumer.py` |
| `server/tests/strategy/test_api.py` | `tests/server/services/strategy/api/test_api.py` |
| `server/tests/strategy/test_t0_endpoint_migration.py` | `tests/server/services/strategy/api/test_t0_endpoint_migration.py` |

> `test_t0_endpoint_migration.py` 虽名带 "t0"，内容测的是 strategy REST 端点的 user_def 迁移（4 个 t0_* 端点的 JOIN 行为），归 `api/`。
> `server/tests/strategy/__init__.py` 与 `server/tests/` 在迁移后变空，**整个 `server/tests/` 目录删除**。

**Client — vitest（25 .test.js + setup-view.js → 整目录平移）**

`client/tests/` 整目录 → `tests/client/`。子目录结构与文件全部平移（`components/ composables/ lib/ modules/ smoke/ stores/ utils/ views/ + setup-view.js`），**内部 `'../setup-view'` 相对导入自动保持**（相对深度不变）。

**hq — pytest（1 文件）**

`hq/test_hqserver.py` → `tests/hq/test_hqserver.py`。

### 配置文件改动（3 处）

| 文件 | 改动 |
|---|---|
| `pytest.ini` | `testpaths = hq` → `testpaths = tests`（pytest 自动收集 `tests/` 下所有 `test_*.py`） |
| `client/vitest.config.js` | 迁到 `tests/client/vitest.config.js`；`include` 与 `environmentMatchGlobs` 路径指 `../tests/client/`；`@` alias 重写为 `../../client/src` |
| `client/package.json` | `"test": "vitest run"` → `"test": "vitest run --config ../tests/client/vitest.config.js"`；`test:watch` 同改 |
| `conftest.py` | 顶部注释：`python -m pytest server/ -v` → `pytest tests/`（顺手清理过时命令，不影响功能） |

### 验证脚本

```bash
# 1. Python 测试
pytest tests/ -v

# 2. 前端测试
cd client && npm test

# 3. 旧目录清理核查
ls server/tests/ 2>/dev/null   # 应不存在
ls client/tests/ 2>/dev/null   # 应不存在
ls hq/test_hqserver.py 2>/dev/null  # 应不存在
```

## Impact

### 新增文件（28 个测试 + 3 个配置）

```
tests/server/services/strategy/
├── models/test_models.py                       (新迁)
├── repository/test_repository.py               (新迁)
├── indicators/test_indicators.py               (新迁)
├── flags/test_flags.py                         (新迁)
├── regime/test_regime.py                       (新迁)
├── grid/test_grid.py                           (新迁)
├── engine/test_engine.py                       (新迁)
├── quote_consumer/test_quote_consumer.py       (新迁)
└── api/
    ├── test_api.py                             (新迁)
    └── test_t0_endpoint_migration.py           (新迁)

tests/client/                                   (整目录平移)
├── setup-view.js
├── components/trade/TodayOrdersPanel.test.js
├── components/trade/TodayTradesPanel.test.js
├── composables/useQuickT0.test.js
├── composables/useT0Keybindings.test.js
├── composables/useT0Quota.test.js
├── composables/useT0Stats.test.js
├── composables/useT0TradeButtons.test.js
├── lib/t0-calc.test.js
├── modules/strategy/GridEditor.test.js
├── modules/strategy/RegimeEditor.test.js
├── modules/strategy/StrategyMonitor.test.js
├── smoke/history-query.test.js
├── smoke/today-flow.test.js
├── stores/holdings.test.js
├── stores/holdings_idb.test.js
├── stores/strategy.test.js
├── utils/date.test.js
├── utils/orderCalc.test.js
├── utils/trdDateFilter.test.js
├── views/HistoryOrders.test.js
├── views/HistoryTrades.test.js
├── views/StrategyTrade.test.js
├── views/T0Trade.test.js
└── views/Trade.test.js

tests/hq/test_hqserver.py                       (新迁)

tests/client/vitest.config.js                   (新迁 + 路径重写)
```

### 删除文件

- `server/tests/strategy/__init__.py`
- `server/tests/strategy/test_models.py`
- `server/tests/strategy/test_repository.py`
- `server/tests/strategy/test_indicators.py`
- `server/tests/strategy/test_flags.py`
- `server/tests/strategy/test_regime.py`
- `server/tests/strategy/test_grid.py`
- `server/tests/strategy/test_engine.py`
- `server/tests/strategy/test_quote_consumer.py`
- `server/tests/strategy/test_api.py`
- `server/tests/strategy/test_t0_endpoint_migration.py`
- `server/tests/`（整个目录）
- `client/tests/`（整个目录，含 __pycache__ 等自动生成）
- `client/vitest.config.js`（旧位置）
- `hq/test_hqserver.py`

### 修改文件（3 个）

- `pytest.ini`（1 行）
- `client/package.json`（2 个 scripts）
- `conftest.py`（顶部注释，不影响功能）

### 不在范围

- ❌ `docs/specs-history/*` 与 `docs/superpowers/plans/*` 中**历史**文档对 `server/tests/strategy/` / `client/tests/` 的引用——属历史记录，不回溯篡改
- ❌ 任何生产代码（`server/`、`client/src/`、`hq/hqserver.py`）——本次只动测试与配置
- ❌ `.github/workflows/`——本仓库不存在 CI 配置
- ❌ `setup.py` / `scripts/evctl.py`——未引用测试路径
- ❌ `evtrade.egg-info/`——自动生成
- ❌ `client/src/` 下的任何源代码——`@` alias 调整是配置侧，不动源码
- ❌ 删除 `__pycache__/` —— git 自动忽略，无需手动操作

## Spec Deltas

### ADDED — `server-architecture/spec.md`

- **REQ-ARCH-006: 测试目录强制约束**
  - 所有测试文件 SHALL 位于 `tests/` 根下
  - 子目录布局：`tests/<area>/<sub>/`，`<area>` ∈ `{server, client, hq}`，与生产代码所在根目录一一对应
  - 当生产代码是 `server/services/strategy/<sub>.py`（子包），测试 MUST 落在 `tests/server/services/strategy/<sub>/test_*.py`
  - 测试目录 SHALL NOT 包含 `__init__.py`（与现有 `tests/server/` 平铺风格一致）
  - CI 检查：`tests/server/test_layer_dependencies.py::test_no_tests_outside_tests_root` —— 遍历整个仓库，确保 `tests/` 外无 `test_*.py` / `*_test.py` / `*.test.js` / `*.spec.js` / `*.test.mjs` / `*.spec.mjs`

### MODIFIED — `view-testing-stack/spec.md`

- `client/tests/setup-view.js` → `tests/client/setup-view.js`
- `client/tests/views/**` → `tests/client/views/**`
- `client/tests/components/**` → `tests/client/components/**`
- `client/tests/composables/**` → `tests/client/composables/**`
- `client/tests/stores/**` → `tests/client/stores/**`
- `client/tests/lib/**` → `tests/client/lib/**`
- `vitest.config.js` 位置：原 `client/vitest.config.js` → 新 `tests/client/vitest.config.js`
- `vitest.config.js` 中 `environmentMatchGlobs` 路径前缀 `tests/` → `../tests/client/`
- `@` alias 原 `./src` → 新 `../../client/src`

### MODIFIED — `view-smoke-automation/spec.md`

- `client/tests/smoke/` → `tests/client/smoke/`
- `cd client && npm test -- --run` 内部加 `--config ../tests/client/vitest.config.js`（通过 `client/package.json` 的 `test` script 实现）

### 不需改的 capability

- **`frontend/spec.md`** —— 全文未引用测试路径（grep `tests/` / `vitest` / `client/tests` / `setup-view` 0 命中），仅引用 `client/src/` 源码路径
- **`quotes/spec.md`** —— 已知问题段提"hqserver 已有 18 个 mock-based 单元测试"（line 117），但**未指明路径**，无需改
- **`strategy/spec.md`** —— 全文未引用 `server/tests/strategy/*.py` 路径，无需改
- **`trading/spec.md` / `push/spec.md` / `auth/spec.md` 等业务 spec** —— 与"测试位置"无关，本 change 不动

## Tasks

详见 [`tasks.md`](./tasks.md)。

## Risks

- 🟡 **`tests/server/test_layer_dependencies.py` 需新增 `test_no_tests_outside_tests_root`**——这是新规约的 CI 锚点，写错会让规约名存实亡
- 🟡 **前端 `npm test` 链路变更**：`cd client && npm test` 仍可用（vitest --config 指新位置），但 CI / 文档若有 hard-coded `cd client && npx vitest` 需同步改——本次仓库内未发现（已 grep 过 `.github/` / `scripts/` / `*.md` / `*.json` / `setup.py`，均无）
- 🟢 测试文件本身内容 0 改动（纯迁移），不应破测试
- 🟢 `conftest.py` 顶部注释只动文档字符串，不影响 conftest 行为

## 不在本 change 范围

- ❌ 各 capability 的业务 spec（`trading` / `push` / `data-model` 等）——本次只影响"测试位置"规约本身
- ❌ 测试本身的覆盖率 / 质量提升——本次只迁位置
- ❌ `server/services/strategy/` 子模块 deep import 收敛（远程 `2026-07-05-strategy_trade` 已豁免于 REQ-ARCH-004，由后续 PR 处理）
- ❌ `docs/` 静态文档中已归档的 `server/tests/strategy/` 历史引用——保留为历史快照