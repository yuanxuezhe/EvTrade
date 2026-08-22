<!--
  StrategyOrder.vue — 策略下单 (编排页面)

  4 面板 (顶部 2 + 下方 1 + 1 联动):
    ① 策略下单 (StrategyOrderCreatePanel) — 顶部左
    ② 行情面板 (QuotePanel)               — 顶部右, 跟选中母单 stock_code 联动
    ③ 策略母单 (StrategyOrderList)        — 中部, 选中触发详情+子单
    ④ 委托子单 (StrategyOrderChildren)    — 底部左, 联动选中母单.task_id
    ⑤ 母单元数据 (StrategyOrderDetail)    — 底部右, 联动选中母单

  本页面仅做布局编排 (≤250 行硬约束), 业务逻辑全部在子组件。
-->
<template>
  <div class="so-view fade-in-up" data-el="strategy-order-view">
    <header class="so-header">
      <h3 class="so-title">策略下单</h3>
      <div class="so-actions">
        <el-button :icon="Refresh" size="small" @click="reloadAll" data-el="so-refresh">刷新</el-button>
      </div>
    </header>

    <!-- 顶部: 创建 + 行情 -->
    <div class="so-top">
      <StrategyOrderCreatePanel
        ref="createPanelRef"
        @created="onOrderCreated"
      />
      <el-card v-if="selectedStockCode" shadow="never" class="so-quote-card" data-el="so-quote-card">
        <template #header>
          <div class="so-card-head">
            <span>行情 · {{ selectedStockCode }}</span>
          </div>
        </template>
        <QuotePanel :stock-code="selectedStockCode" />
      </el-card>
    </div>

    <!-- 中部: 母单列表 -->
    <StrategyOrderList
      :orders="orders"
      :loading="ordersLoading"
      :selected-id="selectedId"
      @select="onOrderSelected"
      @refresh="reloadAll"
    />

    <!-- 底部: 子单 + 元数据 -->
    <div class="so-bottom">
      <StrategyOrderChildren :selected-order="selectedOrder" />
      <el-card shadow="never" class="so-detail-card" data-el="so-detail-card">
        <template #header>
          <div class="so-card-head">
            <span>母单元数据</span>
            <span v-if="selectedOrder" class="so-card-sub">#{{ selectedOrder.task_id }}</span>
          </div>
        </template>
        <StrategyOrderDetail :order="selectedOrder" />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { scriptStrategyApi } from '../api/script_strategy'
import { useHoldingsStore } from '../stores/holdings'
import QuotePanel from '../components/QuotePanel.vue'
import StrategyOrderCreatePanel from '../components/strategy-order/StrategyOrderCreatePanel.vue'
import StrategyOrderList from '../components/strategy-order/StrategyOrderList.vue'
import StrategyOrderDetail from '../components/strategy-order/StrategyOrderDetail.vue'
import StrategyOrderChildren from '../components/strategy-order/StrategyOrderChildren.vue'

const orders = ref([])
const ordersLoading = ref(false)
const selectedOrder = ref(null)
const createPanelRef = ref(null)

// 选中的母单 stock_code (驱动行情面板)
const selectedStockCode = computed(() => selectedOrder.value?.stock_code || '')
const selectedId = computed(() => selectedOrder.value?.id || null)

async function reloadAll() {
  ordersLoading.value = true
  try {
    orders.value = (await scriptStrategyApi.listStrategyOrders()) || []
    // 保持选中 (刷新后 id 仍存)
    if (selectedOrder.value) {
      const found = orders.value.find(o => o.id === selectedOrder.value.id)
      selectedOrder.value = found || null
    }
  } catch (e) {
    ElMessage.error(`加载母单失败: ${e?.response?.data?.detail?.msg || e.message}`)
  } finally {
    ordersLoading.value = false
  }
  createPanelRef.value?.reload?.()
}

function onOrderSelected(row) {
  selectedOrder.value = row
}

function onOrderCreated() {
  reloadAll()
}

onMounted(async () => {
  await reloadAll()
  // 确保 holdings store 已加载 (供子单面板订阅)
  try {
    await useHoldingsStore().bootstrap?.()
  } catch (e) {
    // 持仓 bootstrap 失败不阻断 (子单面板会显示空)
  }
})
</script>

<style scoped>
.so-view { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.so-header {
  display: flex; align-items: center; justify-content: space-between;
}
.so-title { margin: 0; font-size: 18px; font-weight: 600; }
.so-top { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.so-bottom { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; }
.so-card-head { display: flex; justify-content: space-between; align-items: baseline; }
.so-card-sub { color: var(--el-text-color-secondary); font-size: 12px; }
.so-quote-card :deep(.quote-panel) { margin: 0; }
@media (max-width: 1100px) {
  .so-top, .so-bottom { grid-template-columns: 1fr; }
}
</style>
