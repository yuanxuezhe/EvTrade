<!--
  TodayOrdersPanel.vue — 今日委托 mini 面板

  数据源: useHoldingsStore().orders (Pinia + IDB write-through)
  严格过滤: trd_date === activeTrdDate + exclude cancel-row
  嵌在 Trade.vue 右侧 (与下单表单同屏)
  click-to-cancel: 委托行点'撤' → ElMessageBox.confirm → orderStore.cancelOrder
  滚动进度条: 行数 > 表格可视高度时, 底部进度条 + 滚动百分比提示
-->
<template>
  <div class="tp-shell content-card">
    <div class="tp-header">
      <h3 class="tp-title">今日委托</h3>
      <div class="tp-header-right">
        <span class="tp-count text-mono">{{ todayOrders.length }} 笔</span>
        <button
          class="tp-icon-btn"
          @click="refresh"
          :class="{ spinning: refreshing }"
          title="刷新"
        >
          <el-icon><Refresh /></el-icon>
        </button>
      </div>
    </div>

    <div class="tp-body" ref="bodyRef">
      <el-table
        :data="todayOrders"
        :show-overflow-tooltip="true"
        :max-height="bodyMaxHeight"
        stripe
        size="small"
        v-loading="refreshing"
        class="tp-table"
      >
        <el-table-column prop="order_time" label="时间" width="78">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="68">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="代码" width="100">
          <template #default="{ row }">
            <span class="tp-stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="56">
          <template #default="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="量" align="right" width="68" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价" align="right" width="80" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="92">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="56" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canCancel(row)"
              link
              type="danger"
              size="small"
              :loading="orderStore.cancelling && cancellingOrderNo === row.order_no"
              @click="handleCancel(row)"
            >
              撤
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日委托" :image-size="80" />
        </template>
      </el-table>
    </div>

    <!-- 滚动进度条: 表格内容超过可视高度时显示 -->
    <div v-if="scrollProgress > 0" class="tp-scroll-progress">
      <el-progress
        :percentage="Math.round(scrollProgress)"
        :stroke-width="3"
        :show-text="false"
        :color="brandPrimary"
      />
      <span class="tp-scroll-hint text-mono">
        {{ todayOrders.length }} 笔 · 已滚 {{ Math.round(scrollProgress) }}%
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { formatMoney, formatNumber } from '../../utils/format'
import OrderStatusBadge from '../OrderStatusBadge.vue'
import { useHoldingsStore } from '../../stores/holdings'
import { useOrderStore } from '../../stores/order'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()

// 当日委托: trd_date === activeTrdDate + 排除 cancel-row (volume=0 会污染统计口径)
const todayOrders = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.orders.filter(
    (o) => o.trd_date === day && Number(o.order_flag) !== 1
  )
})

const refreshing = ref(false)
const cancellingOrderNo = ref('')

const bodyRef = ref(null)
const bodyMaxHeight = ref('calc(100vh - 280px)')
const scrollProgress = ref(0)

const brandPrimary = '#4f7cff'

// 可撤状态: 非撤单审计 + 状态不在终态集
const TERMINAL_STATUSES = new Set(['51', '52', '53', '54', '55', '56', '57'])
function canCancel(row) {
  if (Number(row.order_flag) === 1) return false
  return !TERMINAL_STATUSES.has(String(row.status))
}

async function refresh() {
  refreshing.value = true
  try {
    await holdingsStore.refreshAll()
  } finally {
    refreshing.value = false
  }
}

async function handleCancel(row) {
  try {
    await ElMessageBox.confirm(
      `确认撤销 ${row.stock_code} 委托 ${row.volume}@${formatMoney(row.price)}？`,
      '撤单确认',
      {
        confirmButtonText: '确认撤单',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  cancellingOrderNo.value = row.order_no
  try {
    await orderStore.cancelOrder(row.order_no, row.trd_date)
    ElMessage.success('已发送撤单请求, 等待 broker 回报')
  } catch (e) {
    // 错误已由 axios 拦截器弹 ElMessage.error
  } finally {
    cancellingOrderNo.value = ''
  }
}

// 滚动进度条: 监听 el-table 内部 el-scrollbar 的 scroll
let resizeObserver = null
let scrollEl = null

function updateScrollProgress() {
  if (!scrollEl) return
  const max = scrollEl.scrollHeight - scrollEl.clientHeight
  if (max <= 0) {
    scrollProgress.value = 0
    return
  }
  const pct = (scrollEl.scrollTop / max) * 100
  scrollProgress.value = Math.min(100, Math.max(0, pct))
}

function attachScrollListener() {
  if (!bodyRef.value) return
  // el-table 内部的滚动容器选择器
  scrollEl = bodyRef.value.querySelector('.el-scrollbar__wrap')
  if (!scrollEl) return
  scrollEl.addEventListener('scroll', updateScrollProgress, { passive: true })
  // 监听容器尺寸变化 (新增行时触发)
  resizeObserver = new ResizeObserver(() => updateScrollProgress())
  resizeObserver.observe(scrollEl)
  // 初次同步
  nextTick(updateScrollProgress)
}

onMounted(() => {
  nextTick(attachScrollListener)
})

onBeforeUnmount(() => {
  if (scrollEl) {
    scrollEl.removeEventListener('scroll', updateScrollProgress)
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
})
</script>