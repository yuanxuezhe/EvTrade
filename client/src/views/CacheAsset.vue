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
// 字段最小宽度 = header "中文 (english_key)" 字符数 * 14px + padding
const fields = [
  { key: 'id', label: 'ID', width: 130, required: true },
  { key: 'cash', label: '现金', width: 140 },
  { key: 'frozen_cash', label: '冻结资金', width: 160 },
  { key: 'market_value', label: '持仓市值', width: 160 },
  { key: 'total_asset', label: '总资产', width: 150 },
]
</script>
