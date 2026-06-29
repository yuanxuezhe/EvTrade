<!--
  CachePositions.vue — 持仓表 (全 CRUD)
  数据源: useHoldingsStore().positions (v8 单一源架构)
-->
<template>
  <CacheTableView
    :rows-ref="positionsRef"
    key-field="stock_code"
    :fields="fields"
    title="持仓缓存 (positions)"
  />
</template>

<script setup>
import { computed } from 'vue'
import CacheTableView from '../components/CacheTableView.vue'
import { useHoldingsStore } from '../stores/holdings'

const holdingsStore = useHoldingsStore()
const positionsRef = computed({
  get: () => holdingsStore.positions,
  set: (v) => { holdingsStore.positions = v },
})

// 持仓表字段
const fields = [
  { key: 'stock_code', label: '股票代码', width: 140, required: true },
  { key: 'stock_name', label: '股票名称', width: 140 },
  { key: 'last_vol', label: '期初', type: 'number', width: 110 },
  { key: 'today_buy', label: '今买', type: 'number', width: 130 },
  { key: 'today_sell', label: '今卖', type: 'number', width: 130 },
  { key: 'avl_vol', label: '可用', type: 'number', width: 130 },
  { key: 'vol', label: '总持仓', type: 'number', width: 130 },
  { key: 'cost_price', label: '成本价', type: 'number', width: 130 },
  { key: 'market_value', label: '市值', type: 'number', width: 140 },
  { key: 'synced_at', label: '同步时间', width: 200 },
  { key: 'synced_from', label: '来源', width: 160 },
]
</script>
