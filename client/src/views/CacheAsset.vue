<!--
  CacheAsset.vue — 资金表 (singleton, 只改)
  IDB store: asset, keyField: id (固定 'singleton')
-->
<template>
  <CacheTableView
    store-name="asset"
    :fields="fields"
    title="资金缓存 (asset)"
    :allow-add="false"
    :allow-delete="false"
    key-field="id"
    @changed="onChanged"
  />
</template>

<script setup>
import CacheTableView from '../components/CacheTableView.vue'
import { useAssetStore } from '../stores/asset'

// admin 在 cache-viewer 改资金后, 立即从 server 拉最新资金刷新 Pinia,
// 让 Asset.vue 等业务页面看到新数据 (而非旧的内存副本)
async function onChanged() {
  const assetStore = useAssetStore()
  await assetStore.fetchAsset()
}

// 资金表字段 (与 server AssetOut schema 对齐)
// 字段最小宽度 = header "中文 (english_key)" 字符数 * 14px + padding
const fields = [
  { key: 'id', label: 'ID', width: 130, required: true },
  { key: 'cash', label: '现金', width: 140 },
  { key: 'frozen_cash', label: '冻结资金', width: 160 },
  { key: 'market_value', label: '持仓市值', width: 160 },
  { key: 'total_asset', label: '总资产', width: 150 },
]
</script>
