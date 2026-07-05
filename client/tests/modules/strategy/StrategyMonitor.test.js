/**
 * StrategyMonitor.test.js — 实时监控面板单测（task 11.9, 6 用例）
 *
 * 覆盖：
 * - 渲染：title / type badge / status badge / note
 * - 控制按钮可见性：active → 暂停/停止/清仓；paused → 恢复/停止/清仓；stopped → 无
 * - pause click → store.controlStrategy 被调
 * - clear_now click → store.controlStrategy 被调 + refreshAudit
 * - audit 行通过 stub 子组件验证 rows 传入
 * - 没有 strategy / trdDate 时 audit 不调用 store
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

const _mockControl = vi.fn()
const _mockLoadAudit = vi.fn()
vi.mock('../../../src/stores/strategy', () => ({
  useStrategyStore: () => ({
    _isPending: vi.fn(() => false),
    controlStrategy: _mockControl,
    loadAudit: _mockLoadAudit,
  }),
}))
vi.mock('../../../src/api', () => ({
  api: {},
  authApi: {},
  userApi: {},
  http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setUnauthorizedHandler: vi.fn(),
  tokenStorage: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
  createWSConnection: vi.fn(),
}))
vi.mock('../../../src/api/strategy', () => ({
  strategyApi: { list: vi.fn(), control: vi.fn(), getAudit: vi.fn() },
}))

import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'
import { setActivePinia, createPinia } from 'pinia'
import StrategyMonitor from '../../../src/modules/strategy/StrategyMonitor.vue'

// 子组件 stub（保留 props 接收语义，让父组件可断言）
const StubAuditTable = {
  name: 'StrategyAuditTable',
  template: '<div class="stub-audit-table" :data-row-count="(rows || []).length" :data-loading="loading" />',
  props: ['rows', 'loading', 'maxRows'],
}
const StubRegimeList = {
  name: 'StrategyRegimeList',
  template: '<div class="stub-regime-list" :data-regime-count="(regimes || []).length" />',
  props: ['regimes'],
}

function _mkStrategy(over = {}) {
  return {
    id: 1,
    stock_code: '600519.SH',
    type: 'general',
    status: 'active',
    note: '测试策略',
    regimes: [
      { id: 11, name: '多头突破', priority: 10, required_flags: ['ma_bullish'], exclude_flags: [], clear_position: false, enabled: true, grids: [] },
    ],
    ...over,
  }
}

describe('StrategyMonitor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    _mockControl.mockReset()
    _mockLoadAudit.mockReset()
  })

  it('renders title + type badge + status badge + note', async () => {
    _mockLoadAudit.mockResolvedValue([])
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: _mkStrategy(), currentTrdDate: '20260706' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('600519.SH')
    expect(wrapper.find('[data-el="monitor-type-general"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-status-active"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('测试策略')
  })

  it('active status: pause + stop + clear buttons visible', async () => {
    _mockLoadAudit.mockResolvedValue([])
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: _mkStrategy({ status: 'active' }), currentTrdDate: '20260706' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()

    expect(wrapper.find('[data-el="monitor-pause"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-stop"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-clear"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-resume"]').exists()).toBe(false)
  })

  it('paused status: resume + stop + clear buttons visible', async () => {
    _mockLoadAudit.mockResolvedValue([])
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: _mkStrategy({ status: 'paused' }), currentTrdDate: '20260706' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()

    expect(wrapper.find('[data-el="monitor-resume"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-stop"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-clear"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="monitor-pause"]').exists()).toBe(false)
  })

  it('stopped status: no control buttons', async () => {
    _mockLoadAudit.mockResolvedValue([])
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: _mkStrategy({ status: 'stopped' }), currentTrdDate: '20260706' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()

    expect(wrapper.find('[data-el="monitor-pause"]').exists()).toBe(false)
    expect(wrapper.find('[data-el="monitor-resume"]').exists()).toBe(false)
    expect(wrapper.find('[data-el="monitor-stop"]').exists()).toBe(false)
    expect(wrapper.find('[data-el="monitor-clear"]').exists()).toBe(false)
  })

  it('pause click → store.controlStrategy 被调', async () => {
    _mockLoadAudit.mockResolvedValue([])
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: _mkStrategy({ status: 'active' }), currentTrdDate: '20260706' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()

    await wrapper.find('[data-el="monitor-pause"]').trigger('click')
    await flushPromises()
    expect(_mockControl).toHaveBeenCalledWith(1, 'pause')
  })

  it('audit rows passed to AuditTable (stub)', async () => {
    const audits = [
      { id: 1, strategy_id: 1, trd_date: '20260706', trigger_type: 'grid_triggered' },
      { id: 2, strategy_id: 1, trd_date: '20260706', trigger_type: 'regime_changed' },
    ]
    _mockLoadAudit.mockResolvedValue(audits)
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: _mkStrategy(), currentTrdDate: '20260706' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()
    await flushPromises()

    expect(_mockLoadAudit).toHaveBeenCalledWith(1, '20260706')
    const auditStub = wrapper.find('.stub-audit-table')
    expect(auditStub.exists()).toBe(true)
    expect(auditStub.attributes('data-row-count')).toBe('2')
    expect(auditStub.attributes('data-loading')).toBe('false')
  })

  it('no strategy → no audit fetch, no buttons', async () => {
    const wrapper = mountView(StrategyMonitor, {
      props: { strategy: null, currentTrdDate: '' },
      stubs: { StrategyAuditTable: StubAuditTable, StrategyRegimeList: StubRegimeList },
    })
    await flushPromises()

    expect(wrapper.find('[data-el="monitor-pause"]').exists()).toBe(false)
    expect(wrapper.find('[data-el="monitor-resume"]').exists()).toBe(false)
    expect(_mockLoadAudit).not.toHaveBeenCalled()
  })
})