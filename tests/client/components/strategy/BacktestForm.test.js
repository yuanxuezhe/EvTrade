/**
 * BacktestForm.test.js — 类型化回测/扫描表单 (v123, 6.4)
 *
 * 覆盖:
 * - 单次模式: params 默认值来自 schema default, 提交载荷 params 正确
 * - 扫描模式: 类型驱动行 (int/float 起止+步长, 默认带出 min/max/step)
 * - comboSize 笛卡尔积计算 + 软 64 / 硬 512 门禁 (canSubmit)
 * - 扫描提交载荷 param_ranges 形状正确
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'
import BacktestForm from '@/components/strategy/BacktestForm.vue'

const SCHEMA = [
  { key: 'fast', type: 'int', min: 1, max: 5, step: 1, default: 3 },
  { key: 'slow', type: 'int', min: 1, max: 3, step: 1, default: 2 },
  { key: 'mode', type: 'choice', values: ['SMA', 'EMA'], default: 'SMA' },
  { key: 'label', type: 'string', default: 'x' },
]

async function _mount() {
  const wrapper = mountView(BacktestForm, { props: { schema: SCHEMA, visible: false } })
  await wrapper.setProps({ visible: true })  // 触发 _init (watch visible)
  await flushPromises()
  return wrapper
}

describe('BacktestForm', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('单次模式: 参数默认值来自 schema default', async () => {
    const wrapper = await _mount()
    expect(wrapper.vm.mode).toBe('single')
    expect(wrapper.vm.singleParams).toEqual({ fast: 3, slow: 2, mode: 'SMA', label: 'x' })
  })

  it('扫描模式: int/float 默认带出 min/max/step 且 enabled; choice/string 不参与', async () => {
    const wrapper = await _mount()
    wrapper.vm.mode = 'sweep'
    await flushPromises()
    const rows = wrapper.vm.sweepRows
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))
    expect(byKey.fast).toMatchObject({ start: 1, end: 5, step: 1 })
    expect(byKey.slow).toMatchObject({ start: 1, end: 3, step: 1 })
    expect(byKey.fast.enabled).toBeTruthy()   // min/max/step 齐全 → 默认参与扫描
    expect(byKey.slow.enabled).toBeTruthy()
    // choice / string: 默认不参与扫描
    expect(byKey.mode.enabled).toBeFalsy()
    expect(byKey.label.enabled).toBeFalsy()
  })

  it('comboSize = 笛卡尔积 (fast 5 × slow 3 = 15)', async () => {
    const wrapper = await _mount()
    wrapper.vm.mode = 'sweep'
    await flushPromises()
    expect(wrapper.vm.comboSize).toBe(15)
  })

  it('硬上限 512: 超限 canSubmit=false', async () => {
    const big = [
      { key: 'a', type: 'int', min: 1, max: 10, step: 1, default: 1 },
      { key: 'b', type: 'int', min: 1, max: 10, step: 1, default: 1 },
      { key: 'c', type: 'int', min: 1, max: 10, step: 1, default: 1 },  // 10*10*10=1000 > 512
    ]
    const wrapper = mountView(BacktestForm, { props: { schema: big, visible: false } })
    await wrapper.setProps({ visible: true })
    await flushPromises()
    wrapper.vm.mode = 'sweep'
    await flushPromises()
    expect(wrapper.vm.comboSize).toBe(1000)
    expect(wrapper.vm.canSubmit).toBe(false)
  })

  it('单次提交: payload 含 params + 标的/日期', async () => {
    const wrapper = await _mount()
    wrapper.vm.stock_code = '600519.SH'
    wrapper.vm.dateRange = ['20260101', '20260131']
    wrapper.vm.mode = 'single'
    wrapper.vm.singleParams = { fast: 7, slow: 21, mode: 'EMA', label: 'x' }
    await wrapper.vm.onSubmit()
    const payload = wrapper.emitted('submit')[0][0]
    expect(payload.mode).toBe('single')
    expect(payload.stock_code).toBe('600519.SH')
    expect(payload.backtest_start_date).toBe('20260101')
    expect(payload.backtest_end_date).toBe('20260131')
    expect(payload.params).toEqual({ fast: 7, slow: 21, mode: 'EMA', label: 'x' })
  })

  it('扫描提交: payload 含 param_ranges (int 起止+步长 / choice 值列表)', async () => {
    const wrapper = await _mount()
    wrapper.vm.stock_code = '000001.SZ'
    wrapper.vm.dateRange = ['20260101', '20260131']
    wrapper.vm.mode = 'sweep'
    wrapper.vm.sweepRows = [
      { key: 'fast', type: 'int', enabled: true, start: 1, end: 3, step: 1 },
      { key: 'slow', type: 'int', enabled: false, start: 1, end: 3, step: 1 },
      { key: 'mode', type: 'choice', enabled: true, valuesStr: 'SMA,EMA' },
      { key: 'label', type: 'string', enabled: true, value: 'y' },
    ]
    await wrapper.vm.onSubmit()
    const payload = wrapper.emitted('submit')[0][0]
    expect(payload.mode).toBe('sweep')
    expect(payload.param_ranges).toEqual({
      fast: { type: 'int', start: 1, end: 3, step: 1 },
      mode: { type: 'choice', values: ['SMA', 'EMA'] },
      label: { type: 'string', value: 'y' },
    })
    expect(payload.metric).toBe('sharpe')
  })
})
