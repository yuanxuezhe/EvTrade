import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api'
import { bulkReplace, touchLastWrite } from '../utils/idbStore'

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
      // api 拦截器已解包 {code,msg,list} → list 数组
      const resp = await api.getAsset()
      const list = Array.isArray(resp) ? resp : (Array.isArray(resp?.list) ? resp.list : [resp])
      const data = list[0] || {}
      asset.value = {
        cash: Number(data.cash) || 0,
        frozen_cash: Number(data.frozen_cash) || 0,
        market_value: Number(data.market_value) || 0,
        total_asset: Number(data.total_asset) || 0
      }
      // write-through 资金表 (1 行 singleton)
      try {
        await bulkReplace('asset', [{ id: 'singleton', ...asset.value }])
        await touchLastWrite()
      } catch (e) {
        console.warn('[asset] IDB write-through 失败:', e)
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