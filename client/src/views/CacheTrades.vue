<!--
  CacheTrades.vue — 成交表 (全 CRUD, 复合主键)
  IDB store: trades, keyField: [trd_date, trade_id]
-->
<template>
  <CacheTableView
    store-name="trades"
    :fields="fields"
    title="成交缓存 (trades)"
    key-field="trd_date,trade_id"
  />
</template>

<script setup>
import CacheTableView from '../components/CacheTableView.vue'

// 成交表字段 (与 server TradeOut schema 对齐)
// keyField 是 [trd_date, trade_id] 复合键, 改 / 删时通过 _formKey 内部处理
const fields = [
  { key: 'trd_date', label: '交易日', width: 110, required: true },
  { key: 'trade_id', label: '成交号', width: 200, required: true },
  { key: 'order_no', label: '委托号', width: 110 },
  { key: 'stock_code', label: '股票代码', width: 110 },
  { key: 'order_type', label: '买卖', width: 80, type: 'select', options: ['23', '24'] },
  { key: 'price', label: '价格', type: 'number', width: 100 },
  { key: 'volume', label: '量', type: 'number', width: 80 },
  { key: 'amount', label: '金额', type: 'number', width: 110 },
  { key: 'trade_time', label: '成交时间', width: 180 },
  { key: 'trade_type', label: '类型', type: 'number', width: 80 },
]
</script>
