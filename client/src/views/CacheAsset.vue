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
  />
</template>

<script setup>
import CacheTableView from '../components/CacheTableView.vue'

// 资金表字段 (与 server AssetOut schema 对齐)
const fields = [
  { key: 'id', label: 'ID', width: 120, required: true },
  { key: 'cash', label: '现金', type: 'number' },
  { key: 'frozen_cash', label: '冻结资金', type: 'number' },
  { key: 'market_value', label: '持仓市值', type: 'number' },
  { key: 'total_asset', label: '总资产', type: 'number' },
]
</script>
