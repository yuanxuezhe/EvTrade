/**
 * useStrategyTrade.js — StrategyTrade view 业务编排（task 12 拆文件保 ≤ 250 行）
 *
 * 职责：
 * - activeTab / selectedId / drafting 状态
 * - currentStrategies / currentStrategy 计算
 * - onSelect / onCreate / cancelDraft / onSubmit / onSave / onDelete 操作
 * - onAddRegime / onRemoveRegime / onAddGrid 嵌套编辑
 * - getTabCount badge
 *
 * UI 不在此文件（保留在 StrategyTrade.vue 模板）
 */
import { computed, ref } from 'vue'
import { useStrategyStore } from '../stores/strategy'
import { useStrategy, TYPE_LABEL } from '../modules/strategy'
import { useHoldingsStore } from '../stores/holdings'

export const TABS = [
  { key: 'general', label: TYPE_LABEL.general || '普通策略' },
  { key: 't0', label: TYPE_LABEL.t0 || 'T0 策略' },
]

function _mkDraft() {
  return {
    stock_code: '',
    type: 'general',
    reference_price: 0,
    base_volume: 100,
    note: '',
    regimes: [],
  }
}

function _todayYYYYMMDD() {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

export function useStrategyTrade() {
  const store = useStrategyStore()
  const { create, update, remove } = useStrategy()
  const holdings = useHoldingsStore()

  // ---- 状态 ----------------------------------------------------------
  const activeTab = ref('general')
  const selectedId = ref(null)
  const drafting = ref(false)
  const draft = ref(_mkDraft())
  const creating = ref(false)
  const saving = ref(false)
  const deleting = ref(false)

  // ---- 计算 ----------------------------------------------------------
  const loading = computed(() => store.loading)
  const currentTrdDate = computed(() => String(holdings.activeTrdDate || _todayYYYYMMDD()))
  const currentStrategies = computed(() => {
    return activeTab.value === 't0' ? store.t0Strategies : store.generalStrategies
  })
  const currentStrategy = computed(() => {
    if (!selectedId.value) return null
    return store.strategies.find((s) => s.id === selectedId.value) || null
  })

  function getTabCount(key) {
    return key === 't0' ? store.t0Strategies.length : store.generalStrategies.length
  }

  // ---- 操作 ----------------------------------------------------------
  function onSelect(id) {
    selectedId.value = id
    drafting.value = false
  }
  function onCreate() {
    drafting.value = true
    selectedId.value = null
    draft.value = _mkDraft()
    draft.value.type = activeTab.value
  }
  function cancelDraft() {
    drafting.value = false
    draft.value = _mkDraft()
  }
  async function onSubmit() {
    if (!draft.value.stock_code || !draft.value.reference_price) return
    creating.value = true
    try {
      const strat = await create(draft.value)
      if (strat) {
        drafting.value = false
        selectedId.value = strat.id
        activeTab.value = strat.type === 't0' ? 't0' : 'general'
      }
    } finally {
      creating.value = false
    }
  }
  async function onSave() {
    if (!currentStrategy.value) return
    saving.value = true
    try {
      await update(currentStrategy.value.id, {
        stock_code: currentStrategy.value.stock_code,
        type: currentStrategy.value.type,
        reference_price: currentStrategy.value.reference_price,
        base_volume: currentStrategy.value.base_volume,
        note: currentStrategy.value.note,
        regimes: currentStrategy.value.regimes,
      })
    } finally {
      saving.value = false
    }
  }
  async function onDelete() {
    if (!currentStrategy.value) return
    deleting.value = true
    try {
      const ok = await remove(currentStrategy.value.id)
      if (ok) selectedId.value = null
    } finally {
      deleting.value = false
    }
  }
  function _mkRegime() {
    return {
      id: null,
      name: `regime-${Date.now()}`,
      priority: 10,
      required_flags: [],
      exclude_flags: [],
      base_volume: null,
      clear_position: false,
      enabled: true,
      grids: [],
    }
  }
  function _mkGrid() {
    return {
      id: null,
      direction: 'buy',
      step_offset: 0,
      trigger_price: 0,
      volume: 100,
      max_fires: null,
      fired_count: 0,
      enabled: true,
      priority: 0,
    }
  }
  function onAddRegime(target) {
    const r = _mkRegime()
    if (target === 'draft') draft.value.regimes.push(r)
    else if (currentStrategy.value) currentStrategy.value.regimes.push(r)
  }
  function onRemoveRegime(idx) {
    if (!currentStrategy.value) return
    currentStrategy.value.regimes.splice(idx, 1)
  }
  function onAddGrid(regimeIdx) {
    const g = _mkGrid()
    if (drafting.value) draft.value.regimes[regimeIdx].grids.push(g)
    else if (currentStrategy.value) currentStrategy.value.regimes[regimeIdx].grids.push(g)
  }

  return {
    TABS,
    // state
    activeTab, selectedId, drafting, draft,
    creating, saving, deleting,
    // computed
    loading, currentTrdDate, currentStrategies, currentStrategy,
    // actions
    getTabCount,
    onSelect, onCreate, cancelDraft, onSubmit, onSave, onDelete,
    onAddRegime, onRemoveRegime, onAddGrid,
  }
}