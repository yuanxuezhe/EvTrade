<!--
  CacheOrders.vue — 委托表 (全 CRUD)
  IDB store: orders, keyField: order_no
-->
<template>
  <CacheTableView
    store-name="orders"
    :fields="fields"
    title="委托缓存 (orders)"
    key-field="order_no"
  />
</template>

<script setup>
import CacheTableView from '../components/CacheTableView.vue'

// 委托表字段 (与 server OrderOut schema 对齐)
const fields = [
  { key: 'order_no', label: '委托号', width: 110, required: true },
  { key: 'trd_date', label: '交易日', width: 110 },
  { key: 'stock_code', label: '股票代码', width: 110 },
  { key: 'order_type', label: '买卖', width: 80, type: 'select', options: ['23', '24'] },
  { key: 'price_type', label: '价格类型', type: 'number', width: 100 },
  { key: 'price', label: '价格', type: 'number', width: 100 },
  { key: 'volume', label: '量', type: 'number', width: 80 },
  { key: 'traded_volume', label: '已成量', type: 'number', width: 90 },
  { key: 'traded_amount', label: '已成额', type: 'number', width: 110 },
  { key: 'avg_price', label: '成交均价', type: 'number', width: 110 },
  { key: 'cancelled_volume', label: '撤单量', type: 'number', width: 90 },
  { key: 'order_flag', label: '标记', type: 'number', width: 80 },
  { key: 'status', label: '状态码', width: 90 },
  { key: 'status_msg', label: '状态描述', width: 130 },
  { key: 'order_id', label: '柜台号', width: 130 },
  { key: 'user_def', label: '自定义', width: 120 },
  { key: 'order_time', label: '委托时间', width: 180 },
]
</script>
