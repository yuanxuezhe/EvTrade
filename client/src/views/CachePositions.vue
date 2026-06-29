<!--
  CachePositions.vue — 持仓表 (全 CRUD)
  IDB store: positions, keyField: stock_code
-->
<template>
  <CacheTableView
    store-name="positions"
    :fields="fields"
    title="持仓缓存 (positions)"
    key-field="stock_code"
    @changed="onChanged"
  />
</template>

<script setup>
import CacheTableView from '../components/CacheTableView.vue'
import { usePositionStore } from '../stores/position'
import { useHoldingsStore } from '../stores/holdings'

// admin 改持仓 IDB 后, 同时刷新 position store 和 holdings store
// (v8 单一源架构: holdings.positions 才是业务页面 Holdings.vue 的真相源)
async function onChanged() {
  const positionStore = usePositionStore()
  await positionStore.fetchPositions()
  // fetchPositions 已经会同步写 holdings.positions (通过 IDB write-through 触发)
  // 但保险起见再显式同步一次, 避免跨 store 时序问题
  const holdingsStore = useHoldingsStore()
  holdingsStore.positions = positionStore.positions
}

// 持仓表字段 (与 server PositionOut schema 对齐)
// width = 字段最小宽度, header 文字 "中文 (key)" 单行能放下
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
