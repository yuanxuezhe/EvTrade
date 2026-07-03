<!--
  TodayTrades.vue — 当日成交通视图（v12）

  数据源：useHoldingsStore().trades（Pinia 内存）
  持久化：IDB write-through（holdings_push.js applyTradePush fire-and-forget）
  严格过滤：trd_date === activeTrdDate（不含历史）

  v8 单一源架构：ws push 自动 merge 到 holdings.trades，本页不调 HTTP
-->
<template>
  <div class="today-trades-view fade-in-up">
    <!-- 交易日状态提示 -->
    <section class="active-day-banner" v-if="activeTrdDate">
      <el-icon><Calendar /></el-icon>
      <span class="banner-label">当前交易日：</span>
      <span class="banner-value text-mono">{{ activeTrdDate }}</span>
      <span class="banner-sep">·</span>
      <span class="banner-count text-mono">{{ todayTrades.length }} 笔</span>
    </section>

    <!-- 概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">成交笔数</div>
        <div class="pill-value text-mono">{{ todayTrades.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">买入笔数</div>
        <div class="pill-value text-mono text-up">{{ buyCount }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">卖出笔数</div>
        <div class="pill-value text-mono text-down">{{ sellCount }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">买入金额</div>
        <div class="pill-value text-mono">¥{{ formatMoney(buyAmount) }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">卖出金额</div>
        <div class="pill-value text-mono">¥{{ formatMoney(sellAmount) }}</div>
      </div>
    </section>

    <!-- 筛选 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索股票代码"
          clearable
          :prefix-icon="Search"
          style="width: 200px"
        />
        <el-select v-model="filters.order_type" placeholder="方向" clearable style="width: 120px">
          <el-option label="买入" value="23" />
          <el-option label="卖出" value="24" />
        </el-select>
        <el-checkbox v-model="filters.includeCancelFill">含撤单审计</el-checkbox>
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="refreshing">刷新</el-button>
        <el-button :icon="Download" @click="exportCSV" :disabled="filteredTrades.length === 0">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table :data="pagedTrades" v-loading="refreshing" style="width: 100%"
                :default-sort="{ prop: 'trade_time', order: 'descending' }">
        <el-table-column prop="trade_time" label="成交时间" width="120">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_time }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="股票代码" width="120">
          <template #default="{ row }">
            <span class="stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_type" label="方向" width="80">
          <template #default="{ row }">
            <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">成交</span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="成交数量" align="right" width="120" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="成交价格" align="right" width="120" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成交金额" align="right" width="140">
          <template #default="{ row }">
            <span class="text-mono">¥{{ formatMoney(localAmount(row)) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_id" label="成交编号" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_id }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日成交" :image-size="100" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredTrades.length"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, Search, Refresh, Download } from '@element-plus/icons-vue'
import { formatMoney, formatNumber } from '../utils/format'
import { useHoldingsStore } from '../stores/holdings'

/**
 * 当日成交通视图（v12）
 *
 * 数据契约（spec/intraday-orders-trades-cache.md）：
 * - 数据源：useHoldingsStore().trades（Pinia 内存 + IDB write-through）
 * - 严格过滤：trd_date === activeTrdDate（不含历史）
 * - 页面挂载 / 路由切换 不发任何 HTTP 请求
 * - 刷新按钮 → holdings.refreshAll()（ws 推送失败兜底）
 * - 金额本地算 = price × volume（与后端 trd_cfm amount 公式一致）
 * - cancel-fill（trade_type=1）默认隐藏，"含撤单审计"复选框显示
 */
const holdingsStore = useHoldingsStore()

const trades = computed(() => holdingsStore.trades)
const activeTrdDate = computed(() => holdingsStore.activeTrdDate)

const todayTrades = computed(() => {
  const day = activeTrdDate.value
  if (!day) return []
  return trades.value.filter((t) => t.trd_date === day)
})

const refreshing = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  keyword: '',
  order_type: '',
  includeCancelFill: false
})

// 统计排除 cancel-fill（trade_type=1）
const _normalTrades = computed(() => todayTrades.value.filter((t) => Number(t.trade_type) !== 1))
const buyCount = computed(() => _normalTrades.value.filter((t) => t.order_type === '23').length)
const sellCount = computed(() => _normalTrades.value.filter((t) => t.order_type === '24').length)
const buyAmount = computed(() =>
  _normalTrades.value.filter((t) => t.order_type === '23').reduce((s, t) => s + t.volume * t.price, 0)
)
const sellAmount = computed(() =>
  _normalTrades.value.filter((t) => t.order_type === '24').reduce((s, t) => s + t.volume * t.price, 0)
)

const filteredTrades = computed(() =>
  todayTrades.value.filter((t) => {
    if (!filters.includeCancelFill && Number(t.trade_type) === 1) return false
    if (filters.keyword && !t.stock_code.toLowerCase().includes(filters.keyword.toLowerCase())) return false
    if (filters.order_type && t.order_type !== filters.order_type) return false
    return true
  })
)

const pagedTrades = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredTrades.value.slice(start, start + pageSize.value)
})

async function refresh() {
  refreshing.value = true
  try {
    await holdingsStore.refreshAll()
  } finally {
    refreshing.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.order_type = ''
  filters.includeCancelFill = false
}

function localAmount(t) {
  // 本地算 price × volume（与后端 trd_cfm amount 公式一致）
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

function exportCSV() {
  const header = ['成交时间', '股票代码', '方向', '类型', '成交数量', '成交价格', '成交金额', '成交编号']
  const rows = filteredTrades.value.map((t) => [
    t.trade_time,
    t.stock_code,
    t.order_type === '23' ? '买入' : (t.order_type === '24' ? '卖出' : t.order_type),
    Number(t.trade_type) === 1 ? '撤单' : '成交',
    t.volume,
    t.price,
    localAmount(t).toFixed(2),
    t.trade_id
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `当日成交_${activeTrdDate.value || ''}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}
</script>

<style scoped>
.today-trades-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.active-day-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-secondary);
}
.banner-label { color: var(--text-secondary); }
.banner-value {
  color: var(--brand-primary);
  font-weight: 600;
  font-size: 14px;
}
.banner-sep { color: var(--text-disabled); margin: 0 4px; }
.banner-count {
  color: var(--text-primary);
  font-weight: 600;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-3);
}
.stat-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pill-label { font-size: 12px; color: var(--text-secondary); }
.pill-value { font-size: 17px; font-weight: 700; }

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  flex-wrap: wrap;
  gap: var(--space-3);
}
.filter-left {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  align-items: center;
}
.filter-right { display: flex; gap: var(--space-2); }

.stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
}

.dir-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 10px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
}
.dir-chip.buy { background: var(--color-up-bg); color: var(--color-up); }
.dir-chip.sell { background: var(--color-down-bg); color: var(--color-down); }

.pagination {
  padding: var(--space-3) var(--space-4);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--border-light);
}

@media (max-width: 1100px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}
</style>