<!--
  CacheAsset.vue — 资金表 (singleton, 只改)
  数据源: useAssetStore().asset (Pinia 内存)
  v8: 资金实际在 holdings.cachedAsset, asset store 是同步镜像
       这里直接改 asset.asset, 通过 watch 自动同步
-->
<template>
  <CacheTableView
    :rows-ref="assetRef"
    key-field="id"
    :fields="fields"
    title="资金缓存 (asset)"
    :allow-add="false"
    :allow-delete="false"
  />
</template>

<script setup>
import { computed } from 'vue'
import CacheTableView from '../components/CacheTableView.vue'
import { useAssetStore } from '../stores/asset'

const assetStore = useAssetStore()
// 直接暴露 store.asset 引用 — Vue 响应式自动双向同步
const assetRef = computed({
  get: () => assetStore.asset,
  set: (v) => { assetStore.asset = v },
})

// 资金表字段
const fields = [
  { key: 'id', label: 'ID', width: 130, required: true },
  { key: 'cash', label: '现金', width: 140 },
  { key: 'available', label: '可用资金', width: 150 },        // v110
  { key: 'frozen_cash', label: '冻结资金', width: 160 },
  { key: 'market_value', label: '持仓市值', width: 160 },
  { key: 'total_asset', label: '总资产', width: 150 },
  { key: 'last_asset', label: '期初总资产', width: 150 },     // v114
]
</script>
