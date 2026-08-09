# view-testing-stack delta — consolidate-tests-under-tests-root（路径从 client/tests 迁到 tests/client）

> change `2026-07-06-consolidate-tests-under-tests-root`
>
> 测试基础设施**功能完全不变**，仅路径从 `client/tests/` 整体平移到 `tests/client/`，相关配置（vitest.config.js）从 `client/` 迁到 `tests/client/`，`@` alias 调整。

## MODIFIED Requirements

### Requirement: view 级别 vitest 测试基础设施（路径修订）

`tests/client/setup-view.js` MUST 提供 view 挂载基础设施（路径原 `client/tests/setup-view.js`）：
- vitest `environmentMatchGlobs` 路由 `tests/client/views/**` + `tests/client/components/**` + `tests/client/smoke/**` 走 jsdom（路径原 `tests/views/**` 等）；`tests/client/composables/**` + `tests/client/stores/**` + `tests/client/lib/**` 保留 happy-dom（性能优先）
- `setup-view.js` MUST stub Element Plus 用到的 17 个组件（ElButton / ElTable / ElTableColumn / ElPagination / ElInput / ElForm / ElFormItem / ElDialog / ElTag / ElEmpty / ElPopover / ElTooltip / ElIcon / ElDatePicker / ElSelect / ElOption / ElCheckbox / ElCard / ElRadioGroup / ElRadioButton / ElDrawer / ElDescriptions / ElDescriptionsItem），保留 Vue 渲染流程（template + slot + props）
- `setup-view.js` MUST stub vue-router（useRouter/useRoute 返回可断言 mock）+ Element Plus icons-vue
- `beforeEach` MUST `setActivePinia(createPinia())` 隔离每个测试的 store 状态
- `global.mountView(component, {props, slots, stubs})` helper MUST 注册 pinia + Element Plus stubs 到全局，返回 vue-test-utils wrapper

### vitest.config.js 位置与配置（修订）

`vitest.config.js` 位置：`tests/client/vitest.config.js`（原 `client/vitest.config.js`）。

新配置的关键路径：
- `include: '../tests/client/**/*.{test,spec}.{js,mjs}'`（原 `tests/**/*.{test,spec}.{js,mjs}`）
- `environmentMatchGlobs` 3 条：
  - `['../tests/client/views/**', 'jsdom']`
  - `['../tests/client/components/**', 'jsdom']`
  - `['../tests/client/smoke/**', 'jsdom']`
- `@` alias 重写：`fileURLToPath(new URL('../../client/src', import.meta.url))`（原 `'./src'`，相对 `tests/client/` 上溯 2 层）

### npm script 修订

`client/package.json` 的 `test` script：
- 旧：`"test": "vitest run"`
- 新：`"test": "vitest run --config ../tests/client/vitest.config.js"`

`test:watch` 同改：`"test:watch": "vitest --config ../tests/client/vitest.config.js"`

### 内部相对导入（不变）

测试文件之间的 `'../setup-view'` / `'../../setup-view'` 相对导入**保持不变**——`client/tests/` → `tests/client/` 整目录平移，相对深度一致：
- `tests/client/views/Trade.test.js` 仍 `import '../setup-view'`
- `tests/client/modules/strategy/StrategyMonitor.test.js` 仍 `import '../../setup-view'`

## Scenarios

#### Scenario: view 测试走 jsdom（路径修订）

- **WHEN** `tests/client/views/HistoryOrders.test.js`（原 `client/tests/views/HistoryOrders.test.js`）头部 `@vitest-environment jsdom`
- **THEN** 加载 jsdom env（DOMRect / ResizeObserver 真实实现）
- **AND** el-table / el-pagination 内部 layout 计算可正常返回非零尺寸

#### Scenario: 现有 happy-dom 测试不受影响（路径修订）

- **WHEN** `tests/client/lib/t0-calc.test.js`（原 `client/tests/lib/t0-calc.test.js`）不带 env pragma
- **THEN** 走 happy-dom（vitest.config.js 默认）
- **AND** 175 旧用例仍全过

#### Scenario: npm test 命令不变

- **WHEN** developer 在 `client/` 目录下跑 `npm test`
- **THEN** vitest 通过 `--config ../tests/client/vitest.config.js` 加载新配置
- **AND** 测试套件全部被发现并执行
- **AND** 行为与迁移前完全一致

#### Scenario: @ alias 仍指向 client/src

- **WHEN** 测试文件 `import X from '@/stores/foo'`
- **THEN** `@` alias 解析到 `client/src/stores/foo.js`（上溯 2 层 + `client/src`）
- **AND** 模块成功加载

## 不在范围

- ❌ view-level 测试基础设施**功能**本身（mountView / flushPromises / setActivePinia / Element Plus stubs / vue-router stub 等）的任何改动
- ❌ smoke 测试覆盖范围（`today-flow.test.js` / `history-query.test.js` 内容）
- ❌ view-testing-stack spec 中的其他 view / composable / store / lib 测试规则