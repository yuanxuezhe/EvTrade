# view-testing-stack Specification

## Purpose
TBD - created by archiving change add-view-level-vitest-stack. Update Purpose after archive.
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

