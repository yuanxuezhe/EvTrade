import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api'
import { useHoldingsStore } from './holdings'

/**
 * 持仓 store Pinia facade（v8 单源架构）
 *
 * 真实数据在 holdings.positions；本 store 通过 computed 暴露持仓列表，
 * view 层继续用 usePositionStore().positions 不变。
 *
 * 保留 own state：
 *   - selectedStockCode / selectedPosition — UI 局部状态（详情抽屉选中项）
 *
 * 设计要点：
 *   - 唯一权威源：holdings.positions（ws pos_cfm 实时更新）
 *   - 本 store 不持有 positions 列表，零数据漂移风险
 *   - fetchPositions delegate 到 holdings.refreshPositions
 */
export const usePositionStore = defineStore('position', () => {
  const holdings = useHoldingsStore()

  // positions 透传
  const positions = computed(() => holdings.positions)

  // UI 局部状态（详情抽屉用，独立于数据源）
  const selectedStockCode = ref(null)
  const selectedPosition = computed(() => {
    if (!selectedStockCode.value) return null
    return positions.value.find((p) => p.stock_code === selectedStockCode.value) || null
  })

  async function fetchPositions() {
    await holdings.refreshPositions()
  }

  async function initPosition(stockCode) {
    await api.initPosition(stockCode)
    await holdings.refreshPositions()
  }

  function selectStock(stockCode) {
    selectedStockCode.value = stockCode
  }

  return {
    positions,
    selectedStockCode,
    selectedPosition,
    fetchPositions,
    initPosition,
    selectStock,
  }
})