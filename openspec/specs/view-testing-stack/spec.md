# view-testing-stack Specification

## Purpose

`client/tests/` 下的 view-level Vitest 测试基础设施（change `add-view-level-vitest-stack`，v9 实施）。

- 提供 jsdom 环境（DOMRect / ResizeObserver 真实实现）+ Element Plus 17+ 组件 stub + vue-router mock + Pinia 隔离
- `global.mountView(component)` helper 一行挂载 view
- 与 `view-smoke-automation` 协作：本 spec 提供"挂载 + 断言"原语，烟雾自动化 spec 覆盖全链路业务状态机

> **与 view-smoke-automation 的边界**：
> - **本 spec（view-testing-stack）**：单 view / 单 component 级别测试；挂载 → 操作 props/slots → 断言渲染结果 + store state
> - **兄弟 spec（view-smoke-automation）**：跨 view + 多 store + mock IDB 的端到端链路测试；模拟"用户完整操作流程"

## Requirements
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

#### Scenario: ElMessageBox.confirm 默认 resolve

- **WHEN** view 调 `await ElMessageBox.confirm(...)` 不指定 mock
- **THEN** 默认 resolve `'confirm'`，等价于用户点确认
- **AND** 测试可通过 `vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')` 模拟取消

#### Scenario: 路由 push 断言

- **WHEN** view 调 `router.push('/history/orders')`
- **THEN** stub 接到调用，测试可断言 `expect(router.push).toHaveBeenCalledWith('/history/orders')`

#### Scenario: store 隔离

- **WHEN** 测试 A 写 `useHoldingsStore().orders.push({...})`
- **THEN** 测试 B 启动时 holdingsStore.orders 为空数组（beforeEach setActivePinia）

#### Scenario: npm test 命令不变

- **WHEN** developer 在 `client/` 目录下跑 `npm test`
- **THEN** vitest 通过 `--config ../tests/client/vitest.config.js` 加载新配置
- **AND** 测试套件全部被发现并执行
- **AND** 行为与迁移前完全一致

#### Scenario: @ alias 仍指向 client/src

- **WHEN** 测试文件 `import X from '@/stores/foo'`
- **THEN** `@` alias 解析到 `client/src/stores/foo.js`（上溯 2 层 + `client/src`）
- **AND** 模块成功加载
