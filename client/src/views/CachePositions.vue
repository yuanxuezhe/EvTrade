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
  />
</template>

<script setup>
import CacheTableView from '../components/CacheTableView.vue'

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
