<!--
  CacheTrades.vue — 成交表 (全 CRUD, 复合主键)
  数据源: useHoldingsStore().trades (v8 单一源)
  复合主键: [trd_date, trade_id]
-->
<template>
  <CacheTableView
    :rows-ref="tradesRef"
    key-field="trd_date,trade_id"
    :fields="fields"
    title="成交缓存 (trades)"
  />
</template>

<script setup>
import { computed } from 'vue'
import CacheTableView from '../components/CacheTableView.vue'
import { useHoldingsStore } from '../stores/holdings'

const holdingsStore = useHoldingsStore()
const tradesRef = computed({
  get: () => holdingsStore.trades,
  set: (v) => { holdingsStore.trades = v },
})

const fields = [
  { key: 'trd_date', label: '交易日', width: 140, required: true },
  { key: 'trade_id', label: '成交号', width: 240, required: true },
  { key: 'order_no', label: '委托编号', width: 140 },
  { key: 'stock_code', label: '股票代码', width: 140 },
  { key: 'order_type', label: '买卖', width: 130, type: 'select', options: ['23', '24'] },
  { key: 'price', label: '价格', type: 'number', width: 120 },
  { key: 'volume', label: '量', type: 'number', width: 110 },
  { key: 'amount', label: '金额', type: 'number', width: 130 },
  { key: 'trade_time', label: '成交时间', width: 200 },
  { key: 'trade_type', label: '类型', type: 'number', width: 120 },
]
</script>
