import { defineStore } from 'pinia'
import { computed } from 'vue'
import { useHoldingsStore } from './holdings'

/**
 * 资金 store Pinia facade（v8 单源架构）
 *
 * 真实数据在 holdings.cachedAsset；本 store 通过 computed 暴露，
 * view 层继续用 useAssetStore().asset 不变。
 *
 * 设计要点：
 *   - 唯一权威源：holdings.cachedAsset（v8 bootstrap 一次性拉取，ws ast_cfm 实时更新）
 *   - 本 store 零独立状态，零数据漂移风险（以前 ws_dispatch 双写到 asset + holdings 会漂移）
 *   - 写操作 (asset = v) 转发到 holdings.cachedAsset（CacheAsset.vue 编辑器需要）
 *   - fetchAsset delegate 到 holdings.refreshAsset（保持原 API）
 */
export const useAssetStore = defineStore('asset', () => {
  const holdings = useHoldingsStore()

  // asset getter/setter: 双向桥接到 holdings.cachedAsset
  const asset = computed({
    get: () => holdings.cachedAsset,
    set: (v) => { holdings.cachedAsset = v },
  })

  // loading 透传
  const loading = computed(() => holdings.loading)

  async function fetchAsset() {
    await holdings.refreshAsset()
  }

  return {
    asset,
    loading,
    fetchAsset,
  }
})