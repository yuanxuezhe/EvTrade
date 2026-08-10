/**
 * ScriptTask.test.js — 两段式编排页: 实盘徽章 + 门禁提示 (v123, 6.4)
 *
 * 覆盖:
 * - 策略有 best_params → 显示"实盘就绪"徽章 (st-live-badge), 实盘按钮可点
 * - 策略无 best_params → 无徽章, 实盘按钮 disabled; 点实盘提示"请先回测生成最优参数"且不调 startLive
 * - 有 best_params 且输入标的 → startLive 被调, 批次刷新 + 选中新 batch
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'
import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'

const mocks = vi.hoisted(() => ({
  listStrategies: vi.fn(),
  getStrategy: vi.fn(),
  listBatches: vi.fn(),
  listBatchTasks: vi.fn(),
  getTask: vi.fn(),
  listScripts: vi.fn(),
  backtestStrategy: vi.fn(),
  startLive: vi.fn(),
  stopTask: vi.fn(),
}))

vi.mock('@/api/script_strategy', () => ({
  scriptStrategyApi: {
    listStrategies: mocks.listStrategies,
    getStrategy: mocks.getStrategy,
    listBatches: mocks.listBatches,
    listBatchTasks: mocks.listBatchTasks,
    getTask: mocks.getTask,
    listScripts: mocks.listScripts,
    backtestStrategy: mocks.backtestStrategy,
    startLive: mocks.startLive,
    stopTask: mocks.stopTask,
  },
}))

vi.mock('@/stores/ws', () => ({
  useWsStore: () => ({ lastTaskProgress: ref(null) }),
}))

import { ElMessage, ElMessageBox } from 'element-plus'
import ScriptTask from '@/views/ScriptTask.vue'

function _strategy(best) {
  return { strategy_id: 1, user_id: 1, script_id: 's1', name: '双均线',
           status: 'draft', best_params: best || null, script: { params_schema: [] } }
}

describe('ScriptTask (实盘门禁 + 徽章)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mocks.listStrategies.mockResolvedValue([{ strategy_id: 1, script_id: 's1', name: '双均线' }])
    mocks.listBatches.mockResolvedValue([])
    mocks.listScripts.mockResolvedValue([])
    mocks.startLive.mockResolvedValue({ batch_no: 2, task_id: 5 })
    ElMessage.warning.mockClear()
  })

  it('有 best_params → 显示"实盘就绪"徽章, liveReady=true', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy({ fast: 5 }))
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.find('[data-el="st-live-badge"]').exists()).toBe(true)
    expect(wrapper.vm.liveReady).toBe(true)
  })

  it('无 best_params → 无徽章, 实盘按钮 disabled; onLive 提示且不调 startLive', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy(null))
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.find('[data-el="st-live-badge"]').exists()).toBe(false)
    expect(wrapper.vm.liveReady).toBe(false)
    // 门禁: 直接调 onLive → 提示 + 阻断
    await wrapper.vm.onLive()
    expect(ElMessage.warning).toHaveBeenCalledWith('请先回测生成最优参数')
    expect(mocks.startLive).not.toHaveBeenCalled()
  })

  it('有 best_params + 输入标的 → startLive 被调', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy({ fast: 5 }))
    ElMessageBox.prompt.mockResolvedValue({ value: '600519.SH' })
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    await wrapper.vm.onLive()
    expect(ElMessageBox.prompt).toHaveBeenCalled()
    expect(mocks.startLive).toHaveBeenCalledWith(1, { stock_code: '600519.SH' })
    expect(mocks.listBatches).toHaveBeenCalledTimes(2)  // 初始 + 实盘后刷新
  })

  it('无 best_params 但强行有值时门禁优先级: 空 best_params 不 startLive', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy({}))
    ElMessageBox.prompt.mockResolvedValue({ value: '600519.SH' })
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    await wrapper.vm.onLive()
    expect(ElMessage.warning).toHaveBeenCalledWith('请先回测生成最优参数')
    expect(mocks.startLive).not.toHaveBeenCalled()
  })
})
