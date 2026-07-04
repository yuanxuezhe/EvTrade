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
  <div class="trade-view fade-in-up" :style="tradeViewStyle">
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
import { useUiStore } from '../stores/ui'

const orderStore = useOrderStore()
const holdings = useHoldingsStore()
const uiStore = useUiStore()
const refreshing = ref(false)
const orderFormRef = ref(null)
const quickStock = ref('')

// OperationLog 高度: 折叠 44px / 展开 320px
//   通过 --oplog-h CSS var 注入 .trade-view
//   让右侧 panel 的 sticky max-height 跟随 OperationLog 变化,避免遮挡
const oplogH = computed(() => (uiStore.oplogExpanded ? '320px' : '44px'))
const tradeViewStyle = computed(() => ({ '--oplog-h': oplogH.value }))

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
/*
 * Trade.vue 布局 (v13 panel 嵌入 + v13.1 上下填满)

 * 整体策略: flex 链 + grid 拆分列
 *   .trade-view         flex column, 填满 .app-content 的可用区
 *   .trade-quicklinks   不缩,固定 32px 高
 *   .trade-grid         flex:1, 占据剩余垂直空间 (填满到 OperationLog 之上)
 *   .trade-form-col     左列 (单格表单), flex column
 *   .trade-panels-col   右列, flex column, sticky + max-height(跟随 --oplog-h)

 * OperationLog 遮挡修复:
 *   --oplog-h 由 uiStore.oplogExpanded 驱动 (折叠 44px / 展开 320px)
 *   右列 max-height: calc(100vh - 80px(header+pad) - var(--oplog-h))
 *   当 OperationLog 展开时,自动收紧
 */
.trade-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

.trade-quicklinks {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.trade-grid {
  display: grid;
  grid-template-columns: 480px 1fr;
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
}

.trade-form-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
  /* 左列内容(下单表单 + 行情) 高度超过行高时,允许内部滚动 */
  overflow: hidden;
}

.trade-panels-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
  /* sticky 让面板跟随滚动; max-height 用 --oplog-h 让 OperationLog 不遮挡 */
  position: sticky;
  top: 80px;
  /* 默认 --oplog-h: 44px (折叠态), 下行表达式:
       calc(100vh - 80 - 44) = 视口高 - header - OperationLog */
  max-height: calc(100vh - 80px - var(--oplog-h, 44px));
}

/* 两个 panel 等分右列高度: 各占一半 (flex:1) */
.trade-panels-col > * {
  flex: 1 1 0;
  min-height: 0;
  /* 防止内部 .tp-body 的内部滚动 + el-table 自带 sticky 冲突 */
  overflow: hidden;
}

@media (max-width: 1100px) {
  .trade-grid { grid-template-columns: 1fr; }
  .trade-form-col {
    overflow: visible;
  }
  .trade-panels-col {
    position: static;
    max-height: none;
    /* 窄屏不强制两端对齐, 让 panel 跟随内容 */
  }
  .trade-panels-col > * {
    flex: 0 0 auto;
    overflow: visible;
  }
}
</style>