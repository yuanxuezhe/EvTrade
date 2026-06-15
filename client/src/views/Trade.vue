<template>
  <div class="trade-view fade-in-up">
    <div class="trade-grid">
      <!-- 左侧：下单表单 + 行情面板 -->
      <div class="trade-form-col">
        <OrderForm
          ref="orderFormRef"
          :on-submit="handleOrderSubmit"
          :default-stock-code="quickStock"
          @update:stock-code="quickStock = $event"
        />

        <!-- 行情面板（替换原快捷选股） -->
        <QuotePanel
          :stock-code="formStockCode"
          @apply-price="onApplyPrice"
        />
      </div>

      <!-- 右侧：今日委托 -->
      <div class="trade-orders-col content-card">
        <div class="orders-header">
          <div>
            <h3 class="orders-title">今日委托</h3>
            <p class="orders-sub">共 {{ orderStore.orders.length }} 笔，{{ pendingCount }} 笔待成交</p>
          </div>
          <div class="orders-actions">
            <el-radio-group v-model="filter" size="small">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="pending">未完成</el-radio-button>
              <el-radio-button value="filled">已成交</el-radio-button>
            </el-radio-group>
            <el-button size="small" :icon="Refresh" @click="refresh" :loading="loading" circle />
          </div>
        </div>

        <el-table :data="filteredOrders" v-loading="loading" style="width: 100%" max-height="640">
          <el-table-column prop="order_time" label="时间" width="90">
            <template #default="{ row }">
              <span class="text-mono text-secondary">{{ row.order_time }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="stock_code" label="股票" width="100">
            <template #default="{ row }">
              <span class="stock-code-cell">{{ row.stock_code }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="order_type" label="方向" width="60">
            <template #default="{ row }">
              <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
                {{ row.order_type === '23' ? '买' : '卖' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="volume" label="数量" align="right" width="100">
            <template #default="{ row }">
              <span class="text-mono">{{ formatNumber(row.volume) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="price" label="价格" align="right" width="100">
            <template #default="{ row }">
              <span class="text-mono">{{ formatMoney(row.price) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="traded_volume" label="已成" align="right" width="80">
            <template #default="{ row }">
              <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="canCancel(row.status)"
                type="danger"
                link
                size="small"
                @click="handleCancel(row.order_id)"
              >
                撤单
              </el-button>
              <span v-else class="text-secondary">—</span>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="今日暂无委托" :image-size="80" />
          </template>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import OrderForm from '../components/OrderForm.vue'
import QuotePanel from '../components/QuotePanel.vue'
import { useOrderStore } from '../stores/order'
import { useWsStore } from '../stores/ws'
import {
  formatMoney, formatNumber
} from '../utils/format'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'

const orderStore = useOrderStore()
const wsStore = useWsStore()
const filter = ref('all')
const quickStock = ref('')
const loading = ref(false)
const orderFormRef = ref(null)

// 行情面板聚焦的股票代码：默认就是当前下单的代码
const formStockCode = computed(() => quickStock.value || '')

// 柜台数字：48 未报 / 49 待报 / 50 已报 / 51 已报待撤 / 52 部成待撤
//           53 部撤 / 54 已撤 / 55 部成 / 56 已成 / 57 废单 / 255 未知
const _PENDING_NUMERIC = new Set(['48', '49', '50', '51', '52', '55'])
const _FILLED_NUMERIC = new Set(['56'])

const pendingCount = computed(() =>
  orderStore.orders.filter((o) => _PENDING_NUMERIC.has(String(o.status || ''))).length
)

const filteredOrders = computed(() => {
  const list = orderStore.orders
  if (filter.value === 'pending') {
    return list.filter((o) => _PENDING_NUMERIC.has(String(o.status || '')))
  }
  if (filter.value === 'filled') {
    return list.filter((o) => _FILLED_NUMERIC.has(String(o.status || '')))
  }
  return list
})

function canCancel(status) {
  // 已报到部成之间可撤；已成/已撤/废单 不可撤
  return _PENDING_NUMERIC.has(String(status || ''))
}

async function handleOrderSubmit(orderData) {
  try {
    await orderStore.placeOrder(orderData)
    await orderStore.fetchOrders()
  } catch (e) {
    // 错误已由 axios 拦截器统一弹 ElMessage.error
  }
}

async function handleCancel(orderId) {
  try {
    await ElMessageBox.confirm('确定要撤销此委托？', '撤单确认', {
      confirmButtonText: '撤单',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await orderStore.cancelOrder(orderId)
    ElMessage.success('撤单成功')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('撤单失败')
  }
}

function onApplyPrice(price) {
  // 行情面板双击价格 → 带入 OrderForm 限价
  if (orderFormRef.value?.onExternalApply) {
    orderFormRef.value.onExternalApply(price)
  }
}

async function refresh() {
  loading.value = true
  try {
    await orderStore.fetchOrders()
  } finally {
    loading.value = false
  }
}

let timer = null
onMounted(async () => {
  loading.value = true
  try {
    await orderStore.fetchOrders()
  } finally {
    loading.value = false
  }
  // 5s 自动刷新委托
  timer = setInterval(() => orderStore.fetchOrders(), 5000)
  // 启动 WS（含 quote_update 频道）
  wsStore.connect()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.trade-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: var(--space-4);
}

.trade-form-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.trade-orders-col {
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
}

.orders-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-3);
}

.orders-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.orders-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.orders-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.stock-code-cell {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-primary);
}

.dir-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  padding: 2px 8px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
}

.dir-chip.buy {
  background: var(--color-up-bg);
  color: var(--color-up);
}

.dir-chip.sell {
  background: var(--color-down-bg);
  color: var(--color-down);
}

@media (max-width: 1100px) {
  .trade-grid {
    grid-template-columns: 1fr;
  }
}
</style>