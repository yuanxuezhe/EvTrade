import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api'
import { bulkReplace, touchLastWrite } from '../utils/idbStore'

export const usePositionStore = defineStore('position', () => {
  const positions = ref([])
  const selectedStockCode = ref(null)

  const selectedPosition = computed(() => {
    if (!selectedStockCode.value) return null
    return positions.value.find(p => p.stock_code === selectedStockCode.value)
  })

  async function fetchPositions() {
    positions.value = await api.getPositions()
    // write-through 持仓表 (keyPath=stock_code, 多行)
    try {
      await bulkReplace('positions', positions.value)
      await touchLastWrite()
    } catch (e) {
      console.warn('[position] IDB write-through 失败:', e)
    }
  }

  async function initPosition(stockCode) {
    await api.initPosition(stockCode)
    await fetchPositions()
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
    selectStock
  }
})