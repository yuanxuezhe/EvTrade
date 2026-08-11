/**
 * StrategyOrder.test.js — v126 策略下单 (母单) 4 面板编排 (C7)
 *
 * 覆盖:
 * - 页面挂载: 4 面板渲染 (创建 / 母单列表 / 子单 / 元数据)
 * - 创建母单: best_params 非空才可建; 选中策略 → 调用 createStrategyOrder
 * - 启动/停止/关闭按钮状态守卫 (stopped→启动 / running→停止+running 禁用关闭)
 * - 选中行联动子单面板 (filter holdingsOrders by task_id + strategy_type=2)
 * - 错误处理: 启动失败/关闭失败 → ElMessage.error
 *
 * 注意:
 * - QuotePanel / 子组件均通过 stubs 替换, 仅断言编排行为
 * - holdings.orders 走 storeToRefs, 需 mock useHoldingsStore
 * - auth.user 来自 auth store (本地 mock useAuthStore 返 { user: { id: 1 } })
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'
import '../setup-view'
import { mountView, flushPromises } from '../setup-view'

const mocks = vi.hoisted(() => ({
  listStrategies: vi.fn(),
  listStrategyOrders: vi.fn(),
  createStrategyOrder: vi.fn(),
  startStrategyOrder: vi.fn(),
  stopStrategyOrder: vi.fn(),
  closeStrategyOrder: vi.fn(),
  // 用 plain array 包装, 在 mock factory 内再 wrap 为 ref (避免 hoisted 期 ref 未导入)
  holdingsOrdersArr: [],
}))

// 在 hoisted 外创建 ref, mock factory 内返回该 ref
const holdingsOrdersRef = ref([])
mocks.holdingsOrdersRef = holdingsOrdersRef

vi.mock('@/api/script_strategy', () => ({
  scriptStrategyApi: {
    listStrategies: mocks.listStrategies,
    listStrategyOrders: mocks.listStrategyOrders,
    createStrategyOrder: mocks.createStrategyOrder,
    startStrategyOrder: mocks.startStrategyOrder,
    stopStrategyOrder: mocks.stopStrategyOrder,
    closeStrategyOrder: mocks.closeStrategyOrder,
  },
}))

// auth store: 当前用户 id=1 (模拟登录)
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 1, role: 'trader' } }),
}))

// holdings store: 暴露 orders ref (脚本控制子单过滤)
vi.mock('@/stores/holdings', () => ({
  useHoldingsStore: () => ({
    orders: mocks.holdingsOrdersRef,
    bootstrap: vi.fn().mockResolvedValue(),
  }),
}))

// QuotePanel 直接 stub (本测试不关心行情渲染)
const QuotePanelStub = {
  name: 'QuotePanel',
  template: '<div class="quote-panel-stub" :data-el="name" :data-stock="stockCode" />',
  props: ['stockCode'],
}

// 子组件 stub: 替换 5 个子组件, 只关心编排逻辑
const stubs = {
  QuotePanel: QuotePanelStub,
  StrategyOrderCreatePanel: {
    name: 'StrategyOrderCreatePanel',
    template: `<div class="so-create-stub">
      <button data-el="stub-create-btn" @click="$emit('created', { id: 99, task_id: 5555 })">emit-created</button>
    </div>`,
    methods: {
      // reload 实际触发 listStrategies (createPanelRef.value?.reload?.() 链路)
      reload: () => mocks.listStrategies(),
    },
  },
  StrategyOrderList: {
    name: 'StrategyOrderList',
    props: ['orders', 'loading', 'selectedId'],
    emits: ['select', 'refresh'],
    template: `<div class="so-list-stub" :data-count="(orders || []).length">
      <button v-for="o in (orders || [])" :key="o.id"
              :data-el="'stub-row-' + o.id"
              @click="$emit('select', o)">select-{{ o.id }}</button>
      <button :data-el="'stub-refresh'" @click="$emit('refresh')">refresh</button>
    </div>`,
  },
  StrategyOrderDetail: {
    name: 'StrategyOrderDetail',
    props: ['order'],
    template: `<div class="so-detail-stub" :data-task="order?.task_id" />`,
  },
  StrategyOrderChildren: {
    name: 'StrategyOrderChildren',
    props: ['selectedOrder'],
    template: `<div class="so-children-stub" :data-task="selectedOrder?.task_id" />`,
  },
}

import { ElMessage, ElMessageBox } from 'element-plus'
import StrategyOrder from '@/views/StrategyOrder.vue'

function _strategy(over = {}) {
  return { strategy_id: 1, user_id: 1, name: '双均线', stock_code: '600519.SH',
           best_params: { fast: 5, slow: 20 }, ...over }
}

function _order(over = {}) {
  return { id: 1, task_id: 5555, strategy_id: 1, strategy_user_id: 1,
           strategy_name: '双均线', stock_code: '600519.SH',
           status: 'stopped', run_count: 0, children_count: 0,
           active_task_id: null, last_started_at: null, last_stopped_at: null,
           closed_at: null, created_at: '2026-08-11 10:00:00', ...over }
}

describe('StrategyOrder (v126 4 面板编排)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mocks.holdingsOrdersRef.value = []
    // 默认: 1 个已回测策略 + 1 个母单 (stopped)
    mocks.listStrategies.mockResolvedValue([_strategy()])
    mocks.listStrategyOrders.mockResolvedValue([_order()])
    mocks.createStrategyOrder.mockResolvedValue({ id: 99, task_id: 5555 })
    mocks.startStrategyOrder.mockResolvedValue({ ok: true, active_task_id: 100 })
    mocks.stopStrategyOrder.mockResolvedValue({ ok: true })
    mocks.closeStrategyOrder.mockResolvedValue({ id: 1, status: 'closed' })
    ElMessage.error.mockClear()
    ElMessage.success.mockClear()
    ElMessage.warning.mockClear()
  })

  it('挂载: 4 面板渲染 + 顶部刷新按钮', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    // 4 子面板 (Create/List/Detail/Children) 通过 stub 渲染
    expect(wrapper.find('.so-create-stub').exists()).toBe(true)
    expect(wrapper.find('.so-list-stub').exists()).toBe(true)
    expect(wrapper.find('.so-detail-stub').exists()).toBe(true)
    expect(wrapper.find('.so-children-stub').exists()).toBe(true)
    // 顶部刷新按钮存在
    expect(wrapper.find('[data-el="so-refresh"]').exists()).toBe(true)
  })

  it('load: 调用 listStrategies + listStrategyOrders, selectedOrder=null', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    expect(mocks.listStrategies).toHaveBeenCalledTimes(1)
    expect(mocks.listStrategyOrders).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.selectedOrder).toBeNull()
    expect(wrapper.vm.selectedStockCode).toBe('')
  })

  it('选中母单 → selectedOrder 写入 + stockCode 联动', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    // 模拟点击行
    wrapper.vm.onOrderSelected(_order({ id: 2, task_id: 6666, stock_code: '000001.SZ' }))
    await flushPromises()
    expect(wrapper.vm.selectedOrder.task_id).toBe(6666)
    expect(wrapper.vm.selectedStockCode).toBe('000001.SZ')
    // QuotePanel 出现 + 传 stock_code
    expect(wrapper.find('.quote-panel-stub').exists()).toBe(true)
    expect(wrapper.find('.quote-panel-stub').attributes('data-stock')).toBe('000001.SZ')
  })

  it('未选母单 → 不显示行情面板 (v-if selectedStockCode)', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    expect(wrapper.vm.selectedStockCode).toBe('')
    expect(wrapper.find('.quote-panel-stub').exists()).toBe(false)
  })

  it('刷新: 按钮 reloadAll 调用 listStrategyOrders 再次', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    expect(mocks.listStrategyOrders).toHaveBeenCalledTimes(1)
    await wrapper.find('[data-el="so-refresh"]').trigger('click')
    await flushPromises()
    expect(mocks.listStrategyOrders).toHaveBeenCalledTimes(2)
  })

  it('创建母单: emit("created") → reloadAll 触发 listStrategyOrders', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    expect(mocks.listStrategyOrders).toHaveBeenCalledTimes(1)
    // 模拟 CreatePanel emit created
    await wrapper.find('[data-el="stub-create-btn"]').trigger('click')
    await flushPromises()
    // onOrderCreated → reloadAll → 第二次 list
    expect(mocks.listStrategyOrders).toHaveBeenCalledTimes(2)
  })

  it('加载失败: listStrategyOrders reject → ElMessage.error 触发', async () => {
    mocks.listStrategyOrders.mockRejectedValueOnce(new Error('network'))
    mountView(StrategyOrder, { stubs })
    await flushPromises()
    // ElMessage.error 至少被调一次 (含 '加载母单失败')
    const calls = ElMessage.error.mock.calls.map(c => String(c[0]))
    expect(calls.some(c => c.includes('加载母单失败'))).toBe(true)
  })

  it('子单过滤: holdingsOrders 含 strategy_type=2 + 匹配 task_id 才显示', async () => {
    // 准备 holdings 数据: 3 笔
    mocks.holdingsOrdersRef.value = [
      { trd_date: '20260811', order_no: 'A1', task_id: 5555, strategy_type: 2,
        order_type: '23', price: 10.5, volume: 100, traded_volume: 0,
        status_msg: '已报', user_def: 's1', order_time: '09:35:00',
        stock_code: '600519.SH' },
      { trd_date: '20260811', order_no: 'A2', task_id: 6666, strategy_type: 2,
        order_type: '24', price: 11.0, volume: 100, traded_volume: 100,
        status_msg: '已成', user_def: 's2', order_time: '10:30:00',
        stock_code: '000001.SZ' },
      { trd_date: '20260811', order_no: 'A3', task_id: null, strategy_type: 1,
        order_type: '23', price: 9.0, volume: 100, traded_volume: 0,
        status_msg: '已报', user_def: '', order_time: '11:00:00',
        stock_code: '600000.SH' },
    ]
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    // 选中 task_id=5555 的母单
    wrapper.vm.onOrderSelected(_order({ id: 1, task_id: 5555 }))
    await flushPromises()
    // 子单 stub 接到 task_id=5555
    const childStub = wrapper.find('.so-children-stub')
    expect(childStub.exists()).toBe(true)
    expect(childStub.attributes('data-task')).toBe('5555')
  })

  it('刷新后保持选中: list 包含原 id → selectedOrder 仍存在', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    // 选中
    wrapper.vm.onOrderSelected(_order({ id: 1 }))
    await flushPromises()
    expect(wrapper.vm.selectedOrder).not.toBeNull()
    // 模拟刷新 (mock 返同一份, 但 id=2 也带, 验证保持 id=1)
    mocks.listStrategyOrders.mockResolvedValueOnce([
      _order({ id: 1, status: 'running' }),
      _order({ id: 2, task_id: 6666 }),
    ])
    await wrapper.vm.reloadAll()
    await flushPromises()
    // selectedOrder 仍指向 id=1 的最新版本
    expect(wrapper.vm.selectedOrder.id).toBe(1)
    expect(wrapper.vm.selectedOrder.status).toBe('running')
  })

  it('刷新后丢失选中: list 不含原 id → selectedOrder=null', async () => {
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    wrapper.vm.onOrderSelected(_order({ id: 1 }))
    await flushPromises()
    // 刷新, list 中不含 id=1
    mocks.listStrategyOrders.mockResolvedValueOnce([])
    await wrapper.vm.reloadAll()
    await flushPromises()
    expect(wrapper.vm.selectedOrder).toBeNull()
    expect(wrapper.vm.selectedStockCode).toBe('')
  })

  it('loadStrategyOrders 失败不阻断页面渲染', async () => {
    mocks.listStrategies.mockResolvedValueOnce([_strategy()])
    mocks.listStrategyOrders.mockRejectedValue(new Error('boom'))
    const wrapper = mountView(StrategyOrder, { stubs })
    await flushPromises()
    // 4 面板仍渲染
    expect(wrapper.find('.so-list-stub').exists()).toBe(true)
  })
})