<template>
  <div class="position-view fade-in-up">
    <!-- 顶部统计 -->
    <section class="pos-stats">
      <div class="stat-pill">
        <div class="pill-label">持仓数</div>
        <div class="pill-value text-mono">{{ positionStore.positions.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">总持仓量</div>
        <div class="pill-value text-mono">{{ formatNumber(totalShares) }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">可用量</div>
        <div class="pill-value text-mono">{{ formatNumber(totalAvailable) }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">今日净变动</div>
        <div class="pill-value text-mono" :class="netChangeClass">
          {{ netChange >= 0 ? '+' : '' }}{{ formatNumber(netChange) }}
        </div>
      </div>
    </section>

    <!-- 工具栏 -->
    <div class="toolbar content-card">
      <div class="toolbar-left">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索股票代码或名称"
          clearable
          :prefix-icon="Search"
          style="width: 280px"
        />
      </div>
      <div class="toolbar-right">
        <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
        <el-button type="warning" @click="goSystemInit">
          <el-icon class="el-icon--right"><Setting /></el-icon>系统初始化
        </el-button>
      </div>
    </div>

    <!-- 持仓表 -->
    <div class="content-card pos-table-wrap">
      <PositionTable
        :positions="filteredPositions"
        :loading="loading"
        @select="handleSelect"
        :selected="positionStore.selectedStockCode"
      />
    </div>

    <!-- 持仓明细抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="`${positionStore.selectedStockCode || ''} - 持仓明细`"
      direction="rtl"
      size="600px"
    >
      <PositionDetail
        v-if="positionStore.selectedStockCode"
        :stock-code="positionStore.selectedStockCode"
        :position="positionStore.selectedPosition"
        :orders="holdingsStore.orders"
        :trades="holdingsStore.trades"
      />
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Setting } from '@element-plus/icons-vue'
import PositionTable from '../components/PositionTable.vue'
import PositionDetail from '../components/PositionDetail.vue'
import { usePositionStore } from '../stores/position'
import { useOrderStore } from '../stores/order'
import { useHoldingsStore } from '../stores/holdings'
import { formatNumber } from '../utils/format'

const router = useRouter()
const positionStore = usePositionStore()
const orderStore = useOrderStore()
const holdingsStore = useHoldingsStore()

const loading = ref(false)
const searchKeyword = ref('')
const drawerVisible = ref(false)

const filteredPositions = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return positionStore.positions
  return positionStore.positions.filter(
    (p) =>
      p.stock_code.toLowerCase().includes(kw) ||
      (p.stock_name || '').toLowerCase().includes(kw)
  )
})

const totalShares = computed(() =>
  positionStore.positions.reduce((sum, p) => sum + (p.vol || 0), 0)
)

const totalAvailable = computed(() =>
  positionStore.positions.reduce((sum, p) => sum + (p.avl_vol || 0), 0)
)

// v12: today_buy/today_sell 已从 Position 删除
// netChange (今日净变动) 改为基于 trades 当前激活日聚合
const netChange = computed(() => {
  const trades = holdingsStore.trades || []
  const activeDay = (holdingsStore.activeTrdDate || '').toString()
  let buyVol = 0
  let sellVol = 0
  for (const t of trades) {
    if (t.trd_date && t.trd_date !== activeDay) continue
    if (t.order_type === '23') buyVol += Number(t.volume) || 0
    else if (t.order_type === '24') sellVol += Number(t.volume) || 0
  }
  return buyVol - sellVol
})

const netChangeClass = computed(() => {
  if (netChange.value > 0) return 'text-up'
  if (netChange.value < 0) return 'text-down'
  return ''
})

async function refresh() {
  loading.value = true
  try {
    await positionStore.fetchPositions()
  } finally {
    loading.value = false
  }
}

function handleSelect(stockCode) {
  positionStore.selectStock(stockCode)
  // v8: 该股委托/成交走 holdings.orders/trades 全量缓存 + ws push 增量更新
  drawerVisible.value = true
}

function goSystemInit() {
  router.push('/system-init')
}

onMounted(async () => {
  loading.value = true
  try {
    await positionStore.fetchPositions()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.position-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
}

.pos-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

.stat-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  transition: all var(--transition-fast);
}

.stat-pill:hover {
  border-color: var(--brand-primary);
  box-shadow: var(--shadow-sm);
}

.pill-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.pill-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
}

.toolbar-right {
  display: flex;
  gap: var(--space-3);
}

.pos-table-wrap {
  padding: var(--space-2);
  overflow: hidden;
}

@media (max-width: 960px) {
  .pos-stats { grid-template-columns: repeat(2, 1fr); }
}
</style>
