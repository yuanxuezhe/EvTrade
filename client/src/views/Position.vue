<template>
  <div class="position-page">
    <div class="header">
      <h2>持仓管理</h2>
      <el-button type="warning" @click="handleInit">日初初始化</el-button>
    </div>

    <PositionTable :positions="positionStore.positions" @select="handleSelect" />

    <PositionDetail
      v-if="positionStore.selectedStockCode"
      :stock-code="positionStore.selectedStockCode"
      :position="positionStore.selectedPosition"
      :orders="orderStore.orders"
      :trades="orderStore.trades"
    />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { usePositionStore } from '../stores/position'
import { useOrderStore } from '../stores/order'
import { ElMessage, ElMessageBox } from 'element-plus'
import PositionTable from '../components/PositionTable.vue'
import PositionDetail from '../components/PositionDetail.vue'

const positionStore = usePositionStore()
const orderStore = useOrderStore()

onMounted(async () => {
  await positionStore.fetchPositions()
})

function handleSelect(stockCode) {
  positionStore.selectStock(stockCode)
  orderStore.fetchOrders(stockCode)
  orderStore.fetchTrades(stockCode)
}

async function handleInit() {
  try {
    await ElMessageBox.confirm(
      '确认进行日初初始化？将重置所有标的的今日买卖数据。',
      '日初初始化',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
    for (const pos of positionStore.positions) {
      await positionStore.initPosition(pos.stock_code)
    }
    ElMessage.success('日初初始化完成')
  } catch {
    // cancelled
  }
}
</script>

<style scoped>
.position-page {
  max-width: 1200px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.header h2 {
  margin: 0;
}
</style>