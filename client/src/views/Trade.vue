<!--
  Trade.vue — 交易下单页（v32 四宫格重构）

  主体 grid 2x2:
    - 左列 420px (v30 280 + 50% ≈ 420), 右列 1fr 吃剩
    - 左上 (1,1) = OrderForm 下单
    - 左下 (2,1) = QuotePanel 行情
    - 右上 (1,2) = HoldingsPanel 持仓
    - 右下 (2,2) = TodayOrdersPanel 今日委托 (内含 委托/成交 tab)
    - 行高各 1fr, 视觉上四块等大

  历史:
    v32 重构: 5 区布局 → 2x2 四宫格 (左列 420px, 行高 1fr 1fr)
    v30 重构: 5 区布局 → 4 区 (成交并入委托, 左列 22% / 280px)
    v13  / v12 修订: 委托/成交嵌入 mini panel, 删独立路由
-->
<template>
  <div class="trade-view fade-in-up" :style="tradeViewStyle" :class="{ 'is-mobile': uiStore.isMobile }">
    <div class="trade-grid">
      <!-- 左上 (1,1) = OrderForm -->
      <div class="trade-cell trade-cell-order">
        <OrderForm
          ref="orderFormRef"
          :on-submit="handleOrderSubmit"
          :default-stock-code="quickStock"
          @update:stock-code="quickStock = $event"
        />
      </div>

      <!-- 左下 (2,1) = QuotePanel -->
      <div class="trade-cell trade-cell-quote">
        <QuotePanel
          :stock-code="formStockCode"
          @apply-price="onApplyPrice"
        />
      </div>

      <!-- 右上 (1,2) = HoldingsPanel -->
      <div class="trade-cell trade-cell-holdings">
        <HoldingsPanel />
      </div>

      <!-- 右下 (2,2) = TodayOrdersPanel (内含委托/成交 tab) -->
      <div class="trade-cell trade-cell-orders">
        <TodayOrdersPanel />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
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

// v35: 滚动条按需显示 — 监听 .el-scrollbar__wrap 的 scrollWidth/clientWidth
//   当 wrap.scrollWidth > clientWidth 时, 给父 .el-scrollbar 加 .has-scroll-x class
//   main.css 只对 .has-scroll-x 强制显示水平滚动条 (修 v32 `display:block !important` 的副作用)
let scrollXObserver = null

function updateScrollXFlags() {
  document.querySelectorAll('.el-table .el-scrollbar__wrap').forEach((wrap) => {
    const sb = wrap.closest('.el-scrollbar')
    if (!sb) return
    // +1 容差: 浮点计算可能让 scrollWidth = clientWidth 但实际有 1px 溢出
    if (wrap.scrollWidth > wrap.clientWidth + 1) sb.classList.add('has-scroll-x')
    else sb.classList.remove('has-scroll-x')
  })
}

onMounted(() => {
  nextTick(() => {
    updateScrollXFlags()
    // ResizeObserver 监测 wrap 大小变化 (窗口缩放/列宽变化)
    scrollXObserver = new ResizeObserver(() => updateScrollXFlags())
    document.querySelectorAll('.el-table .el-scrollbar__wrap').forEach((w) => scrollXObserver.observe(w))
  })
})

onBeforeUnmount(() => {
  scrollXObserver?.disconnect()
  scrollXObserver = null
})

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
 * Trade.vue 布局 (v32 2x2 四宫格)

 * 整体策略: grid 2x2
 *   .trade-view         flex column, 填满 .app-content 的可用区
 *   .trade-grid         grid 模板 1fr 1fr / 420px 1fr, 4 个 cell 各占一格
 *   .trade-cell         flex column, 容纳单个组件, min-width/min-height 0 防止内容溢出
 *
 * OperationLog 遮挡修复 (沿用 v30):
 *   --oplog-h 由 uiStore.oplogExpanded 驱动 (折叠 44px / 展开 320px)
 *   .trade-view 利用 --oplog-h 算出可用高度
 */
.trade-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
  /* v32: 用 --oplog-h 限制实际可用高度,避免右侧 panel 撑出 OperationLog 遮挡区 */
  max-height: calc(100vh - 80px - var(--oplog-h, 44px));
}

.trade-grid {
  display: grid;
  /* v32: 左列 420px (v30 280 + 用户要求 50% 加宽), 行高 1fr 1fr 四宫格
     grid-template-areas 显式指定每格内容, 避免 grid auto-flow 把第二个子元素塞到 (1,2) */
  grid-template-columns: 420px 1fr;
  grid-template-rows: 1fr 1fr;
  grid-template-areas:
    "order holdings"
    "quote orders";
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
}

.trade-cell {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  /* v32 (commit 4): overflow hidden 防止内容溢出到隔壁 cell, 横向滚动由内层 el-scrollbar 处理 */
  overflow: hidden;
}

/* 显式 grid area 绑定, 确保 OrderForm 在左上, QuotePanel 在左下, 持仓在右上, 委托在右下 */
.trade-cell-order    { grid-area: order; }
.trade-cell-quote    { grid-area: quote; }
.trade-cell-holdings { grid-area: holdings; }
.trade-cell-orders   { grid-area: orders; }

/* 左上 OrderForm / 右上 HoldingsPanel 各占自身完整行高 */
.trade-cell-order,
.trade-cell-holdings {
  /* 默认 1fr, 配合 grid-template-rows 已自动等分 */
}

/* 左下 QuotePanel / 右下 TodayOrdersPanel 各占自身完整行高 */
.trade-cell-quote,
.trade-cell-orders {
  /* 默认 1fr, 配合 grid-template-rows 已自动等分 */
}

@media (max-width: 1100px) {
  /* 窄屏回退到单列堆叠 */
  .trade-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
  .trade-cell {
    overflow: visible;
    min-height: 240px;
  }
}

/*
 * v37: 手机竖屏布局优化 (兼容 useUiStore().isMobile)
 *   - 触发条件: ui store isMobile=true (URL ?mobile=1 或 window <= 900)
 *   - 策略: 单列垂直堆叠, OrderForm/QuotePanel/HoldingsPanel/TodayOrdersPanel 顺序排
 *   - 持仓/委托/成交 表: 改卡片式 (display:block + 每行变卡片), 避免横向滚动看不到关键数据
 *   - QuotePanel 盘口: 单列竖排 (卖1→卖5 / 买1→买5), 不再左右两列
 *   - 取消主视口 height 限制, 让用户自然滚动
 */
.trade-view.is-mobile {
  max-height: none;  /* 移动端不限制高度, 让用户自然滚动 */
  gap: var(--space-3);
}
.trade-view.is-mobile .trade-grid {
  grid-template-columns: 1fr;
  grid-template-rows: auto;
  grid-template-areas:
    "order"
    "quote"
    "holdings"
    "orders";
  gap: var(--space-3);
}
.trade-view.is-mobile .trade-cell {
  overflow: hidden;
  min-height: auto;
  /* 移动端每个面板给出最小舒适高度 */
}
.trade-view.is-mobile .trade-cell-order    { min-height: 280px; }
.trade-view.is-mobile .trade-cell-quote    { min-height: 360px; }
.trade-view.is-mobile .trade-cell-holdings { min-height: 320px; }
.trade-view.is-mobile .trade-cell-orders   { min-height: 320px; }
</style>