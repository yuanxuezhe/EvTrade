/**
 * ScriptTask.test.js — 两段式编排页: 我的/公开区分 + 公开开关 + 标的绑定 (v125)
 *
 * 覆盖:
 * - owner: 显示 公开/私有 开关 + 标的; onTogglePublic → updateStrategy({is_public})
 * - 他人公开策略: 只读 (isOwner=false, 批次不加载)
 * - 新建策略: 缺标的拒绝; 有标的 → createStrategy 含 stock_code
 * - 实盘入口已移除 (无 onLive / liveReady)
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
  updateStrategy: vi.fn(),
  createStrategy: vi.fn(),
  stopTask: vi.fn(),
  retestBatch: vi.fn(),
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
    updateStrategy: mocks.updateStrategy,
    createStrategy: mocks.createStrategy,
    stopTask: mocks.stopTask,
    retestBatch: mocks.retestBatch,
  },
}))

vi.mock('@/stores/ws', () => ({
  useWsStore: () => ({ lastTaskProgress: ref(null) }),
}))

import { ElMessage } from 'element-plus'
import ScriptTask from '@/views/ScriptTask.vue'

function _strategy(over = {}) {
  return { strategy_id: 1, user_id: 1, script_id: 's1', name: '双均线',
           status: 'draft', is_public: false, stock_code: '600519.SH',
           best_params: null, script: { params_schema: [] }, ...over }
}

function _login(uid) {
  // v125: auth store 读 localStorage['evtrade-user'], 非旧键 'user'
  localStorage.setItem('evtrade-user', JSON.stringify({ id: uid }))
}

describe('ScriptTask (v125 可见性 + 标的)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    _login(1)
    mocks.listStrategies.mockResolvedValue([
      { strategy_id: 1, user_id: 1, script_id: 's1', name: '双均线', is_public: false, stock_code: '600519.SH' },
    ])
    mocks.listBatches.mockResolvedValue([])
    mocks.listScripts.mockResolvedValue([])
    mocks.getTask.mockResolvedValue({})
    ElMessage.warning.mockClear()
  })

  it('owner: isOwner=true, 显示标的; onTogglePublic → updateStrategy({is_public:true})', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy())
    mocks.updateStrategy.mockResolvedValue(_strategy({ is_public: true }))
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.vm.isOwner).toBe(true)
    expect(wrapper.vm.strategyDetail.stock_code).toBe('600519.SH')
    await wrapper.vm.onTogglePublic(true)
    expect(mocks.updateStrategy).toHaveBeenCalledWith(1, { is_public: true })
    expect(wrapper.vm.strategyDetail.is_public).toBe(true)
  })

  it('他人公开策略 → 只读: isOwner=false, 批次不加载', async () => {
    mocks.listStrategies.mockResolvedValue([
      { strategy_id: 2, user_id: 99, script_id: 's1', name: '他人策略', is_public: true, stock_code: '000001.SZ' },
    ])
    mocks.getStrategy.mockResolvedValue(
      _strategy({ strategy_id: 2, user_id: 99, is_public: true, stock_code: '000001.SZ', script: null })
    )
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.vm.isOwner).toBe(false)
    expect(mocks.listBatches).not.toHaveBeenCalled()
  })

  it('新建策略: 缺标的拒绝; 有标的 → createStrategy 含 stock_code', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy())
    mocks.createStrategy.mockResolvedValue(_strategy())
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    wrapper.vm.openCreate()
    wrapper.vm.createForm.name = '新策略'
    wrapper.vm.createForm.script_id = 's1'
    await wrapper.vm.onCreateStrategy()
    expect(ElMessage.warning).toHaveBeenCalledWith('请填写策略绑定标的')
    expect(mocks.createStrategy).not.toHaveBeenCalled()
    wrapper.vm.createForm.stock_code = '600519.SH'
    await wrapper.vm.onCreateStrategy()
    expect(mocks.createStrategy).toHaveBeenCalledWith({
      name: '新策略', script_id: 's1', stock_code: '600519.SH',
    })
  })

  it('实盘入口已移除 (无 onLive / liveReady)', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy({ best_params: { fast: 5 } }))
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.vm.onLive).toBeUndefined()
    expect(wrapper.vm.liveReady).toBeUndefined()
  })
})
