<!--
  Trade.vue — 交易下单页（v30 整体布局重构: 5 区参考图布局）

  主体 grid 2 列:
    - 左列: OrderForm 下单 + QuotePanel 行情 (flex 等分左列高度)
      左列宽度 280px (约 22%, 适合窄列输入表单)
    - 右列: HoldingsPanel (持仓, flex:2) + TodayOrdersPanel (今日委托, flex:1)
      - 成交(当日) 状态在 TodayOrdersPanel 委托行内嵌 (成交量/状态列), 不再单独 panel
      - 持仓占大头 (flex:2), 委托占小头 (flex:1), 比例近似 2:1

  历史:
    v30 重构: 5 区布局 (下单/行情/持仓/委托/成交) → 4 区 (成交并入委托, 左列 22%)
  v13.1 修订: 左列子组件等分 (flex 链填满不留白)
  v13   修订: 委托 / 成交 从外链按钮改为右侧嵌入 mini panel
  v12   修订: 委托 / 成交 曾拆到 /today/orders /today/trades 独立路由 (v13 删除, 由 mini panel 承担)
-->
<template>
  <div class="trade-view fade-in-up" :style="tradeViewStyle">
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

      <!-- 右侧: 持仓 + 委托 mini panel 堆叠 (成交状态内嵌委托行) -->
      <div class="trade-panels-col">
        <HoldingsPanel />
        <TodayOrdersPanel />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import OrderForm from '../components/OrderForm.vue'
import QuotePanel from '../components/QuotePanel.vue'
import TodayOrdersPanel from '../components/trade/TodayOrdersPanel.vue'
import HoldingsPanel from '../components/trade/HoldingsPanel.vue'
import { useOrderStore } from '../stores/order'
import { useUiStore } from '../stores/ui'

const orderStore = useOrderStore()
const uiStore = useUiStore()
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
</script>

<style scoped>
/*
 * Trade.vue 布局 (v13 panel 嵌入 + v13.1 上下填满 + v13.2 quicklinks 删除 + 左列 flex 链填充)

 * 整体策略: flex 链 + grid 拆分列
 *   .trade-view         flex column, 填满 .app-content 的可用区
 *   .trade-grid         flex:1, 占据垂直空间 (填满到 OperationLog 之上)
 *   .trade-form-col     左列 (单格表单), flex column; 子组件 (OrderForm + QuotePanel) 等分左列
 *   .trade-panels-col   右列, flex column, sticky + max-height(跟随 --oplog-h); 子 panel 等分右列

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

.trade-grid {
  display: grid;
  /* v30: 左列 280px (≈22%, 适合窄列表单), 右列 1fr 吃剩 */
  grid-template-columns: 280px 1fr;
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

/* 左列两个组件 (OrderForm + QuotePanel) 等分左列高度 */
.trade-form-col > * {
  flex: 1 1 0;
  min-height: 0;
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

/* v30: 持仓 (HoldingsPanel) 占大头 flex:2, 委托 (TodayOrdersPanel) 占小头 flex:1 */
.trade-panels-col > *:first-child {
  flex: 2 1 0;
  min-height: 0;
  overflow: hidden;
}
.trade-panels-col > *:last-child {
  flex: 1 1 0;
  min-height: 0;
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