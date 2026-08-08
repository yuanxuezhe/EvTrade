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
### Requirement: view 级别 vitest 测试基础设施

`client/tests/setup-view.js` MUST 提供 view 挂载基础设施：
- vitest `environmentMatchGlobs` 路由 `tests/views/**` + `tests/components/**` + `tests/smoke/**` 走 jsdom；`tests/composables/**` + `tests/stores/**` + `tests/lib/**` 保留 happy-dom（性能优先）
- `setup-view.js` MUST stub Element Plus 用到的 17 个组件（ElButton / ElTable / ElTableColumn / ElPagination / ElInput / ElForm / ElFormItem / ElDialog / ElTag / ElEmpty / ElPopover / ElTooltip / ElIcon / ElDatePicker / ElSelect / ElOption / ElCheckbox / ElCard / ElRadioGroup / ElRadioButton / ElDrawer / ElDescriptions / ElDescriptionsItem），保留 Vue 渲染流程（template + slot + props）
- `setup-view.js` MUST stub vue-router（useRouter/useRoute 返回可断言 mock）+ Element Plus icons-vue
- `beforeEach` MUST `setActivePinia(createPinia())` 隔离每个测试的 store 状态
- `global.mountView(component, {props, slots, stubs})` helper MUST 注册 pinia + Element Plus stubs 到全局，返回 vue-test-utils wrapper

#### Scenario: view 测试走 jsdom

- **WHEN** `client/tests/views/HistoryOrders.test.js` 头部 `@vitest-environment jsdom`
- **THEN** 加载 jsdom env（DOMRect / ResizeObserver 真实实现）
- **AND** el-table / el-pagination 内部 layout 计算可正常返回非零尺寸

#### Scenario: 现有 happy-dom 测试不受影响

- **WHEN** `client/tests/lib/t0-calc.test.js` 不带 env pragma
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

