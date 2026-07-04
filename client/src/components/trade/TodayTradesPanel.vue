<!--
  TodayTradesPanel.vue — 今日成交 mini 面板

  数据源: useHoldingsStore().trades (Pinia + IDB write-through)
  严格过滤: trd_date === activeTrdDate + exclude cancel-fill (trade_type=1)
  嵌在 Trade.vue 右侧 (与下单表单 + 委托面板同屏)
  无撤单按钮 (trades 是终态历史, 不可撤)
  滚动进度条: 行数 > 表格可视高度时, 底部进度条 + 滚动百分比提示
-->
<template>
  <div class="tp-shell content-card">
    <div class="tp-header">
      <h3 class="tp-title">今日成交</h3>
      <div class="tp-header-right">
        <span class="tp-count text-mono">{{ todayTrades.length }} 笔</span>
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
        :data="todayTrades"
        :show-overflow-tooltip="true"
        :max-height="bodyMaxHeight"
        stripe
        size="small"
        v-loading="refreshing"
        class="tp-table"
      >
        <el-table-column prop="trade_time" label="时间" width="78">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_time }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="68">
          <template #default="{ row }">
            <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">成交</span>
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
        <el-table-column label="金额" align="right" min-width="100">
          <template #default="{ row }">
            <span class="text-mono">¥{{ formatMoney(localAmount(row)) }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日成交" :image-size="80" />
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
        {{ todayTrades.length }} 笔 · 已滚 {{ Math.round(scrollProgress) }}%
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { formatMoney, formatNumber } from '../../utils/format'
import { useHoldingsStore } from '../../stores/holdings'

const holdingsStore = useHoldingsStore()

// 当日成交: trd_date === activeTrdDate + 排除 cancel-fill (trade_type=1)
const todayTrades = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.trades.filter(
    (t) => t.trd_date === day && Number(t.trade_type) !== 1
  )
})

const refreshing = ref(false)

const bodyRef = ref(null)
const bodyMaxHeight = ref('calc(100vh - 360px)')
const scrollProgress = ref(0)

const brandPrimary = '#4f7cff'

// 本地算 amount (price × volume), 与后端 trd_cfm 公式一致
function localAmount(t) {
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

async function refresh() {
  refreshing.value = true
  try {
    await holdingsStore.refreshAll()
  } finally {
    refreshing.value = false
  }
}

// 滚动进度条
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
  scrollEl = bodyRef.value.querySelector('.el-scrollbar__wrap')
  if (!scrollEl) return
  scrollEl.addEventListener('scroll', updateScrollProgress, { passive: true })
  resizeObserver = new ResizeObserver(() => updateScrollProgress())
  resizeObserver.observe(scrollEl)
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