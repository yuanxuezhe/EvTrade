<template>
  <el-table :data="positions" highlight-current-row @row-click="handleRowClick" style="width: 100%">
    <el-table-column prop="stock_code" label="股票代码" width="120" />
    <el-table-column prop="stock_name" label="股票名称" width="120" />
    <el-table-column prop="initial_position" label="期初" width="100" align="right" />
    <el-table-column prop="today_buy" label="买入" width="100" align="right" />
    <el-table-column prop="today_sell" label="卖出" width="100" align="right" />
    <el-table-column prop="available" label="可用" width="100" align="right" />
    <el-table-column prop="total" label="总持仓" width="100" align="right" />
  </el-table>
</template>

<script setup>
const props = defineProps({
  positions: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['select'])

function handleRowClick(row) {
  emit('select', row.stock_code)
}
</script>