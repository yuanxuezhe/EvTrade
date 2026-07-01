<template>
  <div class="orders-view fade-in-up">
    <!-- 交易日 Tab -->
    <el-tabs v-model="activeTab" class="orders-tabs">
      <el-tab-pane label="仅当日" name="today" />
      <el-tab-pane label="全部" name="all" />
    </el-tabs>

    <!-- 统计概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">委托总数</div>
        <div class="pill-value text-mono">{{ orders.length }}</div>
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
        <div class="pill-label">已撤</div>
        <div class="pill-value text-mono text-secondary">{{ countByStatus.cancelled }}</div>
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
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 120px">
          <el-option v-for="(label, k) in STATUS_LABEL" :key="k" :label="label" :value="k" />
        </el-select>
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
        <el-button :icon="Download" @click="exportCSV" :disabled="filteredOrders.length === 0">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table
        :data="pagedOrders"
        v-loading="loading"
        style="width: 100%"
        :default-sort="{ prop: 'order_time', order: 'descending' }"
      >
        <el-table-column prop="trd_date" label="交易日" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_time" label="时间" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="股票代码" width="120">
          <template #default="{ row }">
            <span class="stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="委托编号" width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="委托类型" width="90">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_type" label="方向" width="80">
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
        <el-table-column label="成交价" align="right" width="100">
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
        <el-table-column prop="price_type" label="类型" width="80">
          <template #default="{ row }">
            <span class="text-secondary">{{ priceTypeLabel(row.price_type) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_id" label="合同序号" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_id }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="无委托记录" :image-size="100" />
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
import { computed, onMounted, ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import { api } from '../api'
import {
  formatMoney, formatAmount, formatNumber, STATUS_LABEL, STATUS_TYPE, priceTypeLabel
} from '../utils/format'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'
import { useHoldingsStore } from '../stores/holdings'
import { filterByTrdDate } from '../utils/trdDateFilter'

/**
 * 委托数据来源：holdings store 缓存（App 启动时已 bootstrap）
 * 页面 mount 时不重新拉取；点击"刷新"按钮才重拉缓存
 */
const holdingsStore = useHoldingsStore()
const orders = computed(() => holdingsStore.orders)
const activeTrdDate = computed(() => holdingsStore.activeTrdDate)
const activeTab = ref('today')
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  keyword: '',
  order_type: '',
  status: ''
})

const countByStatus = computed(() => {
  // 本地推断码（v6）：51=已成 50/56=部成 48/49=待报/已报 52/53/54=已撤类 55=废单
  // 详见 client/src/utils/format.js:STATUS_LABEL
  // v9: cancel-row(order_flag=1) 不计入正常委托统计(volume=0 会污染部成/已成口径)
  const map = { filled: 0, partial: 0, pending: 0, cancelled: 0, rejected: 0 }
  for (const o of orders.value) {
    if (Number(o.order_flag) === 1) continue
    const s = String(o.status || '')
    if (s === '51') map.filled++
    else if (s === '50' || s === '56') map.partial++
    else if (s === '48' || s === '49') map.pending++
    else if (s === '52' || s === '53' || s === '54') map.cancelled++
    else if (s === '55') map.rejected++
  }
  return map
})

const filteredOrders = computed(() => {
  // 1) trd_date 区间筛选 (按当前 Tab: 'today' 严格匹配 activeTrdDate, 'all' 不过滤)
  const trdRange = activeTab.value === 'today' && activeTrdDate.value
    ? { exact: activeTrdDate.value }
    : {}
  const byTrd = filterByTrdDate(orders.value, trdRange)
  // 2) keyword / order_type / status 现有过滤
  return byTrd.filter((o) => {
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
  // 通过 holdings.refreshAll 重拉全量 RPC（统一日志）
  await holdingsStore.refreshAll()
}

function resetFilters() {
  filters.keyword = ''
  filters.order_type = ''
  filters.status = ''
}

function getFillRate(row) {
  // v9: cancel-row(order_flag=1) volume=0 → 0/0 = NaN, 直接显示 100% (撤单审计无成交率概念)
  if (Number(row.order_flag) === 1) return 100
  if (!row.volume) return 0
  return Math.round(((row.traded_volume || 0) / row.volume) * 100)
}

function getProgressColor(status) {
  // 柜台数字：56=已成 55=部成 54/51=已撤/已报待撤 57=废单
  const s = String(status || '')
  if (s === '56') return '#16b572'
  if (s === '55') return '#ffa726'
  if (s === '54' || s === '51' || s === '57') return '#a0aec0'
  return '#5fa8ff'
}

function exportCSV() {
  const header = ['交易日', '时间', '股票代码', '委托编号', '方向', '委托量', '委托价', '成交量', '成交价', '成交金额', '成交率', '状态', '类型', '合同序号']
  const rows = filteredOrders.value.map((o) => [
    o.trd_date,
    o.order_time,
    o.stock_code,
    o.order_no,
    o.order_type === '23' ? '买入' : (o.order_type === '24' ? '卖出' : o.order_type),
    o.volume,
    o.price,
    o.traded_volume,
    o.avg_price,
    o.traded_amount,
    getFillRate(o) + '%',
    STATUS_LABEL[o.status] || o.status,
    priceTypeLabel(o.price_type),
    o.order_id
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const suffix = activeTab.value === 'today' ? '当日' : '全部'
  link.download = `委托查询_${suffix}_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

// 页面挂载不再 fetch — 数据从 holdings 缓存读
// 只有点击"刷新"按钮或推送数据时才更新
</script>

<style scoped>
.orders-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
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
  transition: all var(--transition-fast);
}

.stat-pill:hover {
  border-color: var(--brand-primary);
}

.pill-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.pill-value {
  font-size: 18px;
  font-weight: 700;
}

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
}

.filter-right {
  display: flex;
  gap: var(--space-2);
}

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

.orders-tabs {
  padding: 0 var(--space-4);
}

.orders-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}
</style>
