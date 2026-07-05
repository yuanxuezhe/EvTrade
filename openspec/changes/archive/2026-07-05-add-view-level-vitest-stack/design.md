# Design — add-view-level-vitest-stack

## 1. 栈分层

```
┌─────────────────────────────────────────────┐
│  view-level test (mountView + stub stores)  │  ← 测试目标
├─────────────────────────────────────────────┤
│  setup-view.js (jsdom env, global helpers)  │  ← 基础设施
├─────────────────────────────────────────────┤
│  vitest.config.js (environmentMatchGlobs)   │  ← env 路由
├─────────────────────────────────────────────┤
│  jsdom + Element Plus stub + vue-router     │  ← 第三方
└─────────────────────────────────────────────┘
```

## 2. 关键决策

### 2.1 为什么用 stub 而非 mock Element Plus

Element Plus 内部依赖 teleport / transition / 大量 ref，完整 mock 重且脆。
**选择**：用 `vi.mock('element-plus', async () => ({ default: { ElButton: ..., ElTable: ..., ... } }))` 只 stub 用到的组件，保留 Vue 渲染流程。

### 2.2 为什么用 jsdom 而非 happy-dom

happy-dom 不实现 `getBoundingClientRect` 的尺寸返回，el-table 内部用 `useResizeObserver` 计算列宽，happy-dom 下表格列全部塌陷为 0 宽。
**选择**：view 测试走 jsdom，composables/stores 测试保留 happy-dom（更快）。

### 2.3 烟雾自动化的边界

- **覆盖**：login → 路由 → IDB 命中 → ws push → 调平 → reconcile 全链路状态机
- **不覆盖**：真实 RPC broker 通信、真实 IndexedDB 持久化（仍用 happy-dom Map 模拟）
- **目标**：替代 6.3/6.4 手动验证，可在 CI 跑

## 3. 文件布局

```
client/tests/
├── setup-view.js                          (NEW, ~80 行)
│   - vi.mock('element-plus', ElPlusStub)
│   - vi.mock('vue-router', RouterStub)
│   - global.mountView = (component, opts) => wrapper
│
├── views/                                 (NEW dir)
│   ├── _setup.js                          (mock stores + router)
│   ├── HistoryOrders.test.js              (~60 用例)
│   ├── HistoryTrades.test.js              (~60 用例)
│   ├── Trade.test.js                      (~30 用例)
│   └── T0Trade.test.js                    (~40 用例)
│
├── components/trade/                      (NEW dir)
│   ├── TodayOrdersPanel.test.js           (~25 用例)
│   └── TodayTradesPanel.test.js           (~20 用例)
│
└── smoke/                                 (NEW dir)
    ├── _setup.js                          (E2E 公共)
    ├── today-flow.test.js                 (替代 6.3)
    └── history-query.test.js              (替代 6.4)
```

## 4. setup-view.js 设计

```js
// @vitest-environment jsdom
import { vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

// Element Plus 桩 — 只 stub 用到的组件
vi.mock('element-plus', async () => {
  const stub = (name) => ({
    name,
    template: '<div class="el-stub" :data-el="name"><slot /></div>',
    props: ['modelValue', 'data', 'prop', 'label', 'width', 'align', ...]
  })
  return {
    default: {
      ElButton: stub('ElButton'),
      ElTable: stub('ElTable'),
      ElTableColumn: stub('ElTableColumn'),
      ElPagination: stub('ElPagination'),
      ElInput: stub('ElInput'),
      ElForm: stub('ElForm'),
      ElFormItem: stub('ElFormItem'),
      ElDialog: stub('ElDialog'),
      ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
      ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
      ElTag: stub('ElTag'),
      ElEmpty: stub('ElEmpty'),
      ElPopover: stub('ElPopover'),
      ElTooltip: stub('ElTooltip'),
      ElIcon: stub('ElIcon'),
      ElDatePicker: stub('ElDatePicker'),
      ElSelect: stub('ElSelect'),
      ElOption: stub('ElOption'),
      ElCheckbox: stub('ElCheckbox'),
      ElCard: stub('ElCard'),
    }
  }
})

// vue-router 桩 — 用 memory history
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => ({ push: vi.fn(), replace: vi.fn(), currentRoute: { value: {} } }),
    useRoute: () => ({ params: {}, query: {}, path: '/' })
  }
})

// pinia 隔离
beforeEach(() => setActivePinia(createPinia()))

// 公共 helper
global.mountView = (component, { props = {}, slots = {}, stubs = {} } = {}) => {
  return mount(component, {
    props,
    slots,
    global: {
      plugins: [createPinia()],
      stubs: { ...stubs }
    }
  })
}

global.flushPromises = flushPromises
```

## 5. view 测试模式

```js
// HistoryOrders.test.js 示例
import { mountView } from '../setup-view'
import HistoryOrders from '../../src/views/HistoryOrders.vue'
import { vi } from 'vitest'

// mock API
vi.mock('../../src/api', () => ({
  default: {
    getOrders: vi.fn().mockResolvedValue({ code: 0, list: [...] })
  }
}))

describe('HistoryOrders', () => {
  it('mounts with default date range', async () => {
    const wrapper = mountView(HistoryOrders)
    expect(wrapper.find('.date-picker').exists()).toBe(true)
  })

  it('calls api.getOrders with date range on query button', async () => {
    const wrapper = mountView(HistoryOrders)
    await wrapper.find('.query-btn').trigger('click')
    expect(api.getOrders).toHaveBeenCalledWith(expect.objectContaining({
      startDate: expect.any(String),
      endDate: expect.any(String)
    }))
  })
})
```

## 6. 烟雾自动化模式

```js
// smoke/today-flow.test.js 示例 (替代 6.3)
describe('today flow smoke', () => {
  it('login → bootstrap → IDB 恢复 → ws push → 调平 → reconcile', async () => {
    // 1. login
    const auth = useAuthStore()
    auth.user = { role: 'admin' }

    // 2. bootstrap holdings
    const holdings = useHoldingsStore()
    await holdings.bootstrap()

    // 3. IDB 恢复 (mock)
    const idb = await loadOrdersForDate('20260705')
    expect(idb).toHaveLength(3)

    // 4. ws push 触发
    const push = useWsStore()
    push.simulatePush({ type: 'ord_cfm', order_no: '00000001', status: '50' })
    await flushPromises()
    expect(holdings.orders).toContainEqual(expect.objectContaining({ status: '50' }))

    // 5. 调平
    await api.adjustPosition('600030.SH', { deltaVol: 100 })
    expect(holdings.positions[0].vol).toBe(1100)

    // 6. reconcile
    await api.adminReconcile()
    expect(holdings.positions[0].vol).toBe(1000)  // 调平被冲掉
  })
})
```

## 7. 验证清单

- `cd client && npm test -- --run` → 175 → 350+ 全过
- 新增 view + smoke 测试栈与现有 composables/stores 测试不冲突（environmentMatchGlobs 隔离）
- 单测时间 < 30s（jsdom 慢但 stub Element Plus 抵消）
- `openspec validate add-view-level-vitest-stack --strict` 通过

## 8. 不在 scope

- Playwright 真 e2e（重量 + 浏览器兼容，stub 已覆盖关键路径）
- Storybook / Histoire 视觉回归
- view-level 性能基准（现有 happy-dom 单元够用）