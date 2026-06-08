import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'

export const useAssetStore = defineStore('asset', () => {
  const asset = ref({
    cash: 0,
    frozen_cash: 0,
    market_value: 0,
    total_asset: 0
  })

  async function fetchAsset() {
    asset.value = await api.getAsset()
  }

  return {
    asset,
    fetchAsset
  }
})