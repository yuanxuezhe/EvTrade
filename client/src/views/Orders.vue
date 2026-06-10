<template>
  <div class="orders-view fade-in-up">
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
        <el-select v-model="filters.direction" placeholder="方向" clearable style="width: 120px">
          <el-option label="买入" value="BUY" />
          <el-option label="卖出" value="SELL" />
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
        <el-table-column prop="direction" label="方向" width="80">
          <template #default="{ row }">
            <span class="dir-chip" :class="row.direction === 'BUY' ? 'buy' : 'sell'">
              {{ row.direction === 'BUY' ? '买入' : '卖出' }}
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
        <el-table-column prop="traded_price" label="成交价" align="right" width="100">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.traded_price) }}</span>
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
            <OrderStatusBadge :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column prop="price_type" label="类型" width="80">
          <template #default="{ row }">
            <span class="text-secondary">{{ row.price_type || 'LIMIT' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_id" label="委托编号" min-width="140" show-overflow-tooltip>
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
  formatMoney, formatNumber, STATUS_LABEL, STATUS_TYPE
} from '../utils/format'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'

const orders = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  keyword: '',
  direction: '',
  status: ''
})

const countByStatus = computed(() => {
  const map = { filled: 0, partial: 0, pending: 0, cancelled: 0, rejected: 0 }
  for (const o of orders.value) {
    const s = o.status
    if (s === 'filled') map.filled++
    else if (s === 'partial' || s === 'partial_pending_cancel' || s === 'partial_cancelled') map.partial++
    else if (s === 'unreported' || s === 'pending_report' || s === 'reported' || s === 'pending') map.pending++
    else if (s === 'cancelled' || s === 'reported_cancel') map.cancelled++
    else if (s === 'rejected') map.rejected++
  }
  return map
})

const filteredOrders = computed(() => {
  return orders.value.filter((o) => {
    if (filters.keyword && !o.stock_code.toLowerCase().includes(filters.keyword.toLowerCase())) {
      return false
    }
    if (filters.direction && o.direction !== filters.direction) return false
    if (filters.status && o.status !== filters.status) return false
    return true
  })
})

const pagedOrders = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredOrders.value.slice(start, start + pageSize.value)
})

async function refresh() {
  loading.value = true
  try {
    orders.value = await api.getOrders()
  } catch (e) {
    ElMessage.error('查询失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.direction = ''
  filters.status = ''
}

function getFillRate(row) {
  if (!row.volume) return 0
  return Math.round(((row.traded_volume || 0) / row.volume) * 100)
}

function getProgressColor(status) {
  if (status === 'filled') return '#16b572'
  if (status === 'partial') return '#ffa726'
  if (status === 'cancelled' || status === 'rejected') return '#a0aec0'
  return '#5fa8ff'
}

function exportCSV() {
  const header = ['时间', '股票代码', '方向', '委托量', '委托价', '成交量', '成交价', '状态', '类型', '委托编号']
  const rows = filteredOrders.value.map((o) => [
    o.order_time,
    o.stock_code,
    o.direction === 'BUY' ? '买入' : '卖出',
    o.volume,
    o.price,
    o.traded_volume,
    o.traded_price,
    STATUS_LABEL[o.status] || o.status,
    o.price_type,
    o.order_id
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `委托查询_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

onMounted(refresh)
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
</style>
