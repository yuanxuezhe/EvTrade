<!--
  Trade.vue — 交易下单页（v13 panel 嵌入重构）

  顶部: 快捷链接 + 刷新按钮
  主体 grid 2 列:
    - 左列: OrderForm 下单 + QuotePanel 行情
    - 右列: TodayOrdersPanel + TodayTradesPanel (sticky 跟随滚动)

  v13 修订: 委托 / 成交 从外链按钮改为右侧嵌入 mini panel
  v12 修订: 委托 / 成交 已拆到 /today/orders /today/trades 独立路由 (完整版)
-->
<template>
  <div class="trade-view fade-in-up">
    <!-- 顶部快捷操作 -->
    <div class="trade-quicklinks">
      <el-button text :icon="Refresh" @click="refreshAll" :loading="refreshing" title="刷新 holdings 缓存">
        刷新
      </el-button>
    </div>

    <div class="trade-grid">
      <!-- 左侧: 下单表单 + 行情面板 -->
      <div class="trade-form-col">
        <OrderForm
          ref="orderFormRef"
          :on-submit="handleOrderSubmit"
          :default-stock-code="quickStock"
          @update:stock-code="quickStock = $event"
        />

        <QuotePanel
          :stock-code="formStockCode"
          @apply-price="onApplyPrice"
        />
      </div>

      <!-- 右侧: 委托 + 成交 mini panel 堆叠 -->
      <div class="trade-panels-col">
        <TodayOrdersPanel />
        <TodayTradesPanel />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import OrderForm from '../components/OrderForm.vue'
import QuotePanel from '../components/QuotePanel.vue'
import TodayOrdersPanel from '../components/trade/TodayOrdersPanel.vue'
import TodayTradesPanel from '../components/trade/TodayTradesPanel.vue'
import { useOrderStore } from '../stores/order'
import { useHoldingsStore } from '../stores/holdings'

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
//   正常情况下: WS 推送 → applyOrderPush / applyTradePush → UI 实时更新
//   异常情况: 用户怀疑数据滞后, 点此按钮重拉 4 个 RPC (委托 / 成交 / 持仓 / 资金)
async function refreshAll() {
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
  grid-template-columns: 480px 1fr;
  gap: var(--space-4);
  align-items: start;
}

.trade-form-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.trade-panels-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  position: sticky;
  top: 80px;
  max-height: calc(100vh - 100px);
}

@media (max-width: 1100px) {
  .trade-grid { grid-template-columns: 1fr; }
  .trade-form-col { max-width: none; }
  .trade-panels-col {
    position: static;
    max-height: none;
  }
}
</style>