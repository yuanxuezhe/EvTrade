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
// width = 字段最小宽度, header 文字 "中文 (key)" 单行能放下
const fields = [
  { key: 'trd_date', label: '交易日', width: 140, required: true },
  { key: 'trade_id', label: '成交号', width: 240, required: true },
  { key: 'order_no', label: '委托号', width: 140 },
  { key: 'stock_code', label: '股票代码', width: 140 },
  { key: 'order_type', label: '买卖', width: 130, type: 'select', options: ['23', '24'] },
  { key: 'price', label: '价格', type: 'number', width: 120 },
  { key: 'volume', label: '量', type: 'number', width: 110 },
  { key: 'amount', label: '金额', type: 'number', width: 130 },
  { key: 'trade_time', label: '成交时间', width: 200 },
  { key: 'trade_type', label: '类型', type: 'number', width: 120 },
]
</script>
