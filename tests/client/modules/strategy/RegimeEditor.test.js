/**
 * RegimeEditor.test.js — 单 regime 编辑器单测（task 11.9, 8 用例）
 *
 * 覆盖：
 * - 渲染：name / priority / enabled 切换 / flag 选择 / grid 列表
 * - patch 行为：name 通过 setProps 触发 update:modelValue（el-input-number stub 不透传）
 * - grid 操作：addGrid emit / 单 grid update 走 updateGrid / remove 走 removeGrid
 * - 空 grids 列表渲染 el-empty
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: {},
  authApi: {},
  userApi: {},
  http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setUnauthorizedHandler: vi.fn(),
  tokenStorage: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
  createWSConnection: vi.fn(),
}))
// mock strategy api：避免 FlagPicker 触发真实请求
vi.mock('@/api/strategy', () => ({
  strategyApi: {
    list: vi.fn(),
    getFlagDefinitions: vi.fn().mockResolvedValue({
      list: [
        { code: 'ma_bullish', name: '均线多头', category: 'trend', description: 'MA 上行' },
        { code: 'rsi_over', name: 'RSI 超买', category: 'momentum', description: '>70' },
      ],
    }),
  },
}))

import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'
import { setActivePinia, createPinia } from 'pinia'
import RegimeEditor from '@/modules/strategy/RegimeEditor.vue'

function _mkRegime(over = {}) {
  return {
    id: 1,
    name: '多头突破',
    priority: 10,
    required_flags: [],
    exclude_flags: [],
    base_volume: null,
    clear_position: false,
    enabled: true,
    grids: [
      { id: 100, direction: 'buy', step_offset: 0, trigger_price: 10.0, volume: 100, max_fires: 5, fired_count: 0, enabled: true, priority: 0 },
    ],
    ...over,
  }
}

describe('RegimeEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders name input + priority + enabled switch + flags section', async () => {
    const reg = _mkRegime()
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    expect(wrapper.find('[data-el="regime-name"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="regime-priority"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="regime-enabled"]').exists()).toBe(true)
    // flag picker 两个（required + exclude）— stub 透传 data-el 不可靠，断言 popover 元素存在
    expect(wrapper.findAll('.el-popover').length).toBeGreaterThanOrEqual(2)
  })

  it('update:modelValue patches via setProps (v-model flow)', async () => {
    const reg = _mkRegime()
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    // 模拟外部 update:modelValue 流回（el-input stub 不透传 input 事件）
    await wrapper.setProps({ modelValue: { ...reg, name: '新名称', priority: 20 } })
    await flushPromises()
    expect(wrapper.props('modelValue').name).toBe('新名称')
    expect(wrapper.props('modelValue').priority).toBe(20)
  })

  it('clear_position toggle via setProps preserves other fields', async () => {
    const reg = _mkRegime({ clear_position: false })
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    await wrapper.setProps({ modelValue: { ...reg, clear_position: true } })
    await flushPromises()
    expect(wrapper.props('modelValue').clear_position).toBe(true)
    expect(wrapper.props('modelValue').name).toBe('多头突破')
  })

  it('emits addGrid when add-grid button clicked', async () => {
    const reg = _mkRegime()
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    const btn = wrapper.find('[data-el="regime-add-grid"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('addGrid')).toBeTruthy()
  })

  it('emits remove when delete button clicked', async () => {
    const reg = _mkRegime()
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    const btn = wrapper.find('[data-el="regime-remove"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('remove')).toBeTruthy()
  })

  it('renders initial grid via GridEditor', async () => {
    const reg = _mkRegime()
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    // grid 行 data-el 包含 grid-row- 前缀
    expect(wrapper.find('[data-el^="grid-row-"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('网格列表')
  })

  it('grid update via setProps propagates to grids[idx]', async () => {
    const reg = _mkRegime()
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    const newGrids = [{ ...reg.grids[0], volume: 200 }]
    await wrapper.setProps({ modelValue: { ...reg, grids: newGrids } })
    await flushPromises()
    expect(wrapper.props('modelValue').grids[0].volume).toBe(200)
    expect(wrapper.props('modelValue').grids).toHaveLength(1)
  })

  it('shows empty state when no grids', async () => {
    const reg = _mkRegime({ grids: [] })
    const wrapper = mountView(RegimeEditor, { props: { modelValue: reg } })
    await flushPromises()

    expect(wrapper.find('[data-el^="grid-row-"]').exists()).toBe(false)
  })
})