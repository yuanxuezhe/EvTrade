<template>
  <div class="trade-page">
    <h2>交易面板</h2>

    <div class="trade-content">
      <OrderForm :on-submit="handleOrderSubmit" />

      <div class="order-list">
        <h3>今日委托</h3>
        <el-table :data="orderStore.orders" style="width: 100%">
          <el-table-column prop="order_time" label="时间" width="100" />
          <el-table-column prop="stock_code" label="股票" width="120" />
          <el-table-column prop="direction" label="方向" width="60">
            <template #default="{ row }">
              <span :class="row.direction === 'BUY' ? 'text-buy' : 'text-sell'">
                {{ row.direction === 'BUY' ? '买入' : '卖出' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="volume" label="数量" width="100" align="right" />
          <el-table-column prop="price" label="价格" width="100" align="right">
            <template #default="{ row }">
              {{ row.price.toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'pending'"
                type="danger"
                size="small"
                @click="handleCancel(row.order_id)"
              >
                撤单
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useOrderStore } from '../stores/order'
import { ElMessage } from 'element-plus'
import OrderForm from '../components/OrderForm.vue'

const orderStore = useOrderStore()

onMounted(async () => {
  await orderStore.fetchOrders()
})

async function handleOrderSubmit(orderData) {
  try {
    await orderStore.createOrder(orderData)
    ElMessage.success('下单成功')
  } catch (error) {
    ElMessage.error('下单失败')
  }
}

async function handleCancel(orderId) {
  try {
    await orderStore.cancelOrder(orderId)
    ElMessage.success('撤单成功')
  } catch (error) {
    ElMessage.error('撤单失败')
  }
}

function getStatusType(status) {
  const map = {
    pending: 'warning',
    filled: 'success',
    cancelled: 'info',
    rejected: 'danger'
  }
  return map[status] || 'info'
}
</script>

<style scoped>
.trade-page {
  max-width: 1000px;
}
.trade-content {
  display: flex;
  gap: 20px;
}
.order-list {
  flex: 1;
}
.text-buy { color: #f56c6c; }
.text-sell { color: #67c23a; }
</style>