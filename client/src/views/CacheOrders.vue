<!--
  CacheOrders.vue — 委托表 (全 CRUD)
  数据源: useHoldingsStore().orders (v8 单一源)
-->
<template>
  <CacheTableView
    :rows-ref="ordersRef"
    key-field="order_no"
    :fields="fields"
    title="委托缓存 (orders)"
  />
</template>

<script setup>
import { computed } from 'vue'
import CacheTableView from '../components/CacheTableView.vue'
import { useHoldingsStore } from '../stores/holdings'

const holdingsStore = useHoldingsStore()
const ordersRef = computed({
  get: () => holdingsStore.orders,
  set: (v) => { holdingsStore.orders = v },
})

const fields = [
  { key: 'order_no', label: '委托号', width: 140, required: true },
  { key: 'trd_date', label: '交易日', width: 140 },
  { key: 'stock_code', label: '股票代码', width: 140 },
  { key: 'order_type', label: '买卖', width: 130, type: 'select', options: ['23', '24'] },
  { key: 'price_type', label: '价格类型', type: 'number', width: 140 },
  { key: 'price', label: '价格', type: 'number', width: 120 },
  { key: 'volume', label: '量', type: 'number', width: 110 },
  { key: 'traded_volume', label: '已成量', type: 'number', width: 140 },
  { key: 'traded_amount', label: '已成额', type: 'number', width: 140 },
  { key: 'avg_price', label: '成交均价', type: 'number', width: 140 },
  { key: 'cancelled_volume', label: '撤单量', type: 'number', width: 140 },
  { key: 'order_flag', label: '标记', type: 'number', width: 110 },
  { key: 'status', label: '状态码', width: 130 },
  { key: 'status_msg', label: '状态描述', width: 160 },
  { key: 'order_id', label: '柜台号', width: 160 },
  { key: 'user_def', label: '自定义', width: 140 },
  { key: 'order_time', label: '委托时间', width: 200 },
]
</script>
