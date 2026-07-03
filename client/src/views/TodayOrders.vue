<!--
  TodayOrders.vue — 当日委托视图（v12）

  数据源：useHoldingsStore().orders（Pinia 内存）
  持久化：IDB write-through（holdings_push.js applyOrderPush fire-and-forget）
  严格过滤：trd_date === activeTrdDate（不含历史）

  v8 单一源架构：ws push 自动 merge 到 holdings.orders，本页不调 HTTP
  F5 后：bootstrap → IDB 命中 → 立刻显示 → ws 增量补偿
-->
<template>
  <div class="today-orders-view fade-in-up">
    <!-- 交易日状态提示 -->
    <section class="active-day-banner" v-if="activeTrdDate">
      <el-icon><Calendar /></el-icon>
      <span class="banner-label">当前交易日：</span>
      <span class="banner-value text-mono">{{ activeTrdDate }}</span>
      <span class="banner-sep">·</span>
      <span class="banner-count text-mono">{{ todayOrders.length }} 笔</span>
    </section>

    <!-- 统计概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">委托总数</div>
        <div class="pill-value text-mono">{{ todayOrders.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">已成交</div>
        <div class="pill-value text-mono text-up">{{ countByStatus.filled }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">部成</div>
        <div class="pill-value text-mono">{{ countByStatus.partial }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">待成交</div>
        <div class="pill-value text-mono text-info">{{ countByStatus.pending }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">已撤/废单</div>
        <div class="pill-value text-mono text-secondary">{{ countByStatus.cancelled + countByStatus.rejected }}</div>
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
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px">
          <el-option v-for="(label, k) in STATUS_LABEL" :key="k" :label="label" :value="k" />
        </el-select>
        <el-checkbox v-model="filters.includeCancelRow">含撤单审计</el-checkbox>
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="refreshing">刷新</el-button>
        <el-button :icon="Download" @click="exportCSV" :disabled="filteredOrders.length === 0">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table
        :data="pagedOrders"
        v-loading="refreshing"
        style="width: 100%"
        :default-sort="{ prop: 'order_time', order: 'descending' }"
      >
        <el-table-column prop="order_time" label="时间" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="委托编号" width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="股票代码" width="120">
          <template #default="{ row }">
            <span class="stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_type" label="方向" width="70">
          <template #default="{ row }">
            <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="委托量" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="委托价" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_volume" label="成交量" align="right" width="100">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="均价" align="right" width="100">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.avg_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成交金额" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatAmount(row.traded_amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成交率" min-width="140">
          <template #default="{ row }">
            <div class="ratio-cell">
              <el-progress
                :percentage="getFillRate(row)"
                :stroke-width="6"
                :show-text="false"
                :color="getProgressColor(row.status)"
              />
              <span class="text-mono ratio-num">{{ getFillRate(row) }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
        </el-table-column>
        <el-table-column prop="order_id" label="合同序号" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_id }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日委托" :image-size="100" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredOrders.length"
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
import {
  formatMoney, formatAmount, formatNumber, STATUS_LABEL
} from '../utils/format'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'
import { useHoldingsStore } from '../stores/holdings'

/**
 * 当日委托视图（v12）
 *
 * 数据契约（spec/orders-trades-history-query.md & intraday-orders-trades-cache.md）：
 * - 数据源：useHoldingsStore().orders（Pinia 内存 + IDB write-through）
 * - 严格过滤：trd_date === activeTrdDate（不含历史）
 * - 页面挂载 / 路由切换 不发任何 HTTP 请求（v8 单一源架构）
 * - 刷新按钮 → holdings.refreshAll()（ws 推送失败兜底）
 * - cancel-row（order_flag=1）默认隐藏，"含撤单审计"复选框显示
 */
const holdingsStore = useHoldingsStore()

const orders = computed(() => holdingsStore.orders)
const activeTrdDate = computed(() => holdingsStore.activeTrdDate)

// 当日委托：严格按 trd_date === activeTrdDate 过滤
const todayOrders = computed(() => {
  const day = activeTrdDate.value
  if (!day) return []
  return orders.value.filter((o) => o.trd_date === day)
})

const refreshing = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  keyword: '',
  order_type: '',
  status: '',
  includeCancelRow: false
})

// 状态统计：v11 broker xtconstant 字典 + cancel-row 隔离
const countByStatus = computed(() => {
  const map = { filled: 0, partial: 0, pending: 0, cancelled: 0, rejected: 0 }
  for (const o of todayOrders.value) {
    if (Number(o.order_flag) === 1) continue  // cancel-row 不计入正常统计
    const s = String(o.status || '')
    if (s === '56') map.filled++
    else if (s === '50' || s === '55') map.partial++
    else if (s === '48' || s === '49' || s === '51' || s === '52') map.pending++
    else if (s === '53' || s === '54') map.cancelled++
    else if (s === '57') map.rejected++
  }
  return map
})

const filteredOrders = computed(() => {
  return todayOrders.value.filter((o) => {
    // cancel-row 默认隐藏（v9: volume=0 会污染部成/已成口径）
    if (!filters.includeCancelRow && Number(o.order_flag) === 1) return false
    if (filters.keyword && !o.stock_code.toLowerCase().includes(filters.keyword.toLowerCase())) {
      return false
    }
    if (filters.order_type && o.order_type !== filters.order_type) return false
    if (filters.status && o.status !== filters.status) return false
    return true
  })
})

const pagedOrders = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredOrders.value.slice(start, start + pageSize.value)
})

async function refresh() {
  // 通过 holdings.refreshAll 重拉全量 RPC（兜底, 正常情况 ws 推送已覆盖）
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
  filters.status = ''
  filters.includeCancelRow = false
}

function getFillRate(row) {
  // cancel-row: volume=0 → 直接显示 100%（撤单审计无成交率概念）
  if (Number(row.order_flag) === 1) return 100
  if (!row.volume) return 0
  return Math.round(((row.traded_volume || 0) / row.volume) * 100)
}

function getProgressColor(status) {
  // broker 码: 56=已成 55=部成 54=已撤 53=部成部撤 57=废单
  const s = String(status || '')
  if (s === '56') return '#16b572'
  if (s === '55') return '#ffa726'
  if (s === '54' || s === '53' || s === '57') return '#a0aec0'
  return '#5fa8ff'
}

function exportCSV() {
  const header = ['时间', '委托编号', '类型', '股票代码', '方向', '委托量', '委托价',
                  '成交量', '均价', '成交金额', '成交率', '状态', '合同序号']
  const rows = filteredOrders.value.map((o) => [
    o.order_time,
    o.order_no,
    Number(o.order_flag) === 1 ? '撤单' : '委托',
    o.stock_code,
    o.order_type === '23' ? '买入' : (o.order_type === '24' ? '卖出' : o.order_type),
    o.volume,
    o.price,
    o.traded_volume,
    o.avg_price,
    o.traded_amount,
    getFillRate(o) + '%',
    STATUS_LABEL[o.status] || o.status,
    o.order_id || ''
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `当日委托_${activeTrdDate.value || ''}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}
</script>

<style scoped>
.today-orders-view {
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
  align-items: center;
  justify-content: space-between;
}
.pill-label { font-size: 12px; color: var(--text-secondary); }
.pill-value { font-size: 18px; font-weight: 700; }
.text-info { color: var(--color-info); }

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

.ratio-cell {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.ratio-num {
  min-width: 40px;
  text-align: right;
  font-size: 12px;
  color: var(--text-secondary);
}

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