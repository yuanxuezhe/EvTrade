<template>
  <div class="trade-view fade-in-up">
    <!-- v12: 顶部快捷链接 — 委托 / 成交 已被拆到独立路由 -->
    <div class="trade-quicklinks">
      <el-button :icon="Document" @click="$router.push('/today/orders')">
        今日委托 →
      </el-button>
      <el-button :icon="Money" @click="$router.push('/today/trades')">
        今日成交 →
      </el-button>
      <el-button text :icon="Refresh" @click="refresh" :loading="refreshing" title="刷新 holdings 缓存">
        刷新
      </el-button>
    </div>

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
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Money, Refresh } from '@element-plus/icons-vue'
import OrderForm from '../components/OrderForm.vue'
import QuotePanel from '../components/QuotePanel.vue'
import { useOrderStore } from '../stores/order'
import { useHoldingsStore } from '../stores/holdings'

// v12: 今日委托 / 今日成交 已拆到 /today/orders /today/trades 独立路由
//   本页面聚焦下单 + T0 决策, 委托列表跳转查阅
const orderStore = useOrderStore()
const holdings = useHoldingsStore()
const refreshing = ref(false)
const orderFormRef = ref(null)
const quickStock = ref('')

// 行情面板聚焦的股票代码：默认就是当前下单的代码
const formStockCode = computed(() => quickStock.value || '')

async function handleOrderSubmit(orderData) {
  try {
    // placeOrder 内部已 _upsertToHoldings 写缓存(等 WS 推送二次确认)
    await orderStore.placeOrder(orderData)
  } catch (e) {
    // 错误已由 axios 拦截器统一弹 ElMessage.error
  }
}

function onApplyPrice(price) {
  // 行情面板双击价格 → 带入 OrderForm 限价
  if (orderFormRef.value?.onExternalApply) {
    orderFormRef.value.onExternalApply(price)
  }
}

// 手动刷新按钮（兜底, 不再轮询）
//   正常情况下: WS 推送 → applyOrderPush → UI 实时更新
//   异常情况: 用户怀疑数据滞后, 点此按钮重拉 4 个 RPC
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await holdings.refreshAll()
    ElMessage.success('已刷新')
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  // 不再 onMounted fetch(违反单一源纪律; holdings 已在 AppHeader 启动 bootstrap)
})
</script>

<style scoped>
.trade-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.trade-quicklinks {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}

.trade-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-4);
}

.trade-form-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-width: 480px;
}

@media (max-width: 1100px) {
  .trade-grid { grid-template-columns: 1fr; }
  .trade-form-col { max-width: none; }
}
</style>