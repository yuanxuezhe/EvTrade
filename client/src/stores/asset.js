import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api'

export const useAssetStore = defineStore('asset', () => {
  const asset = ref({
    cash: 0,
    frozen_cash: 0,
    market_value: 0,
    total_asset: 0
  })

  const loading = ref(false)

  async function fetchAsset() {
    loading.value = true
    try {
      const data = await api.getAsset()
      asset.value = {
        cash: Number(data.cash) || 0,
        frozen_cash: Number(data.frozen_cash) || 0,
        market_value: Number(data.market_value) || 0,
        total_asset: Number(data.total_asset) || 0
      }
    } catch (e) {
      console.error('fetchAsset error:', e)
    } finally {
      loading.value = false
    }
  }

  return {
    asset,
    loading,
    fetchAsset
  }
})