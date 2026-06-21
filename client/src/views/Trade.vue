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
            <p class="orders-sub">共 {{ holdings.orders.length }} 笔，{{ pendingCount }} 笔待成交</p>
          </div>
          <div class="orders-actions">
            <el-radio-group v-model="filter" size="small">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="pending">未完成</el-radio-button>
              <el-radio-button value="filled">已成交</el-radio-button>
            </el-radio-group>
            <el-button size="small" :icon="Refresh" @click="refresh" :loading="refreshing" circle title="刷新" />
          </div>
        </div>

        <el-table :data="filteredOrders" v-loading="refreshing" style="width: 100%" max-height="640">
          <el-table-column prop="order_time" label="时间" width="90">
            <template #default="{ row }">
              <span class="text-mono text-secondary">{{ row.order_time }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="order_no" label="单号" width="100" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="text-mono text-secondary">{{ row.order_no }}</span>
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
                @click="handleCancel(row.order_no, row.trd_date)"
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
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import OrderForm from '../components/OrderForm.vue'
import QuotePanel from '../components/QuotePanel.vue'
import { useOrderStore } from '../stores/order'
import { useHoldingsStore } from '../stores/holdings'
import {
  formatMoney, formatNumber, TERMINAL_STATUSES
} from '../utils/format'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'

// v8: 单一缓存源架构
//   - holdings 是权威 (orders/trades ref + applyOrderPush/applyTradePush)
//   - orderStore 只暴露 actions (placeOrder/cancelOrder)
//   - view 不在 onMounted fetch, 不 5s 轮询
const orderStore = useOrderStore()
const holdings = useHoldingsStore()
const filter = ref('all')
const quickStock = ref('')
const refreshing = ref(false)
const orderFormRef = ref(null)

// 行情面板聚焦的股票代码：默认就是当前下单的代码
const formStockCode = computed(() => quickStock.value || '')

// 本地推断码（v6）：48=待报 / 49=已报 / 50=部成（均可撤,非终态）
//   终态 (51/52/53/54/55/56)：51=已成 52=部撤 53=已撤 54=已撤单 55=废单 56=部成部撤
// 详见 client/src/utils/format.js:TERMINAL_STATUSES 与 server/services/push_handlers.py
const _FILLED_NUMERIC = new Set(['51'])  // 已成
const _PENDING_NUMERIC = new Set(['48', '49', '50'])  // 仍可能变化

const pendingCount = computed(() =>
  holdings.orders.filter((o) => !TERMINAL_STATUSES.has(String(o.status || ''))).length
)

const filteredOrders = computed(() => {
  const list = holdings.orders
  if (filter.value === 'pending') {
    return list.filter((o) => !TERMINAL_STATUSES.has(String(o.status || '')))
  }
  if (filter.value === 'filled') {
    return list.filter((o) => _FILLED_NUMERIC.has(String(o.status || '')))
  }
  return list
})

function canCancel(status) {
  // 非终态即可撤 (待报/已报/部成)
  return !TERMINAL_STATUSES.has(String(status || ''))
}

async function handleOrderSubmit(orderData) {
  try {
    // v8: placeOrder 内部已 _upsertToHoldings 写缓存(等 WS 推送二次确认)
    //     删 5s 轮询; 删 fetchOrders() 重复拉
    await orderStore.placeOrder(orderData)
  } catch (e) {
    // 错误已由 axios 拦截器统一弹 ElMessage.error
  }
}

async function handleCancel(orderNo, trdDate) {
  try {
    await ElMessageBox.confirm(`确定要撤销委托 ${orderNo}？`, '撤单确认', {
      confirmButtonText: '撤单',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await orderStore.cancelOrder(orderNo, trdDate)
    ElMessage.success('撤单请求已发送,等待回报')
  } catch (e) {
    if (e === 'cancel') return  // 用户取消
    // 友好处理 BROKER_NOT_READY 等错误
    const detail = e?.response?.data?.detail
    const code = detail?.code
    if (code === 'BROKER_NOT_READY') {
      ElMessage.warning('柜台尚未回报委托号,稍后再试')
    } else if (detail?.msg) {
      ElMessage.error(detail.msg)
    } else {
      ElMessage.error('撤单失败')
    }
  }
}

function onApplyPrice(price) {
  // 行情面板双击价格 → 带入 OrderForm 限价
  if (orderFormRef.value?.onExternalApply) {
    orderFormRef.value.onExternalApply(price)
  }
}

// v8: 手动刷新按钮（兜底, 不再轮询）
//   正常情况下: WS 推送 → applyOrderPush → UI 实时更新
//   异常情况: 用户怀疑数据滞后, 点此按钮重拉 4 个 RPC
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await holdings.refreshAll()
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  // v8: 不再 onMounted fetch(违反单一源纪律; holdings 已在 AppHeader 启动 bootstrap)
  //     不再 5s 轮询(WS 推送已覆盖实时性)
  //     holdings 缓存可能是空的(用户首登 / 切换账号),此处不再做补救
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