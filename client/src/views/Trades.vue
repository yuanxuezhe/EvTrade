<template>
  <div class="trades-view fade-in-up">
    <!-- 概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">成交笔数</div>
        <div class="pill-value text-mono">{{ trades.length }}</div>
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
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
        <el-button :icon="Download" @click="exportCSV" :disabled="filteredTrades.length === 0">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table :data="pagedTrades" v-loading="loading" style="width: 100%"
                :default-sort="{ prop: 'trade_time', order: 'descending' }">
        <el-table-column prop="trd_date" label="交易日" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
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
            <span class="text-mono">¥{{ formatMoney(row.volume * row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_id" label="成交编号" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_id" label="合同序号" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_id }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="无成交记录" :image-size="100" />
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import { api } from '../api'
import { formatMoney, formatNumber } from '../utils/format'
import { useHoldingsStore } from '../stores/holdings'

/** 成交数据来源：holdings store 缓存 */
const holdingsStore = useHoldingsStore()
const trades = computed(() => holdingsStore.trades)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  keyword: '',
  order_type: ''
})

// v9: cancel-fill(trade_type=1) 不计入买/卖统计(它是撤单审计行, 非真实买卖)
const _normalTrades = computed(() => trades.value.filter((t) => Number(t.trade_type) !== 1))
const buyCount = computed(() => _normalTrades.value.filter((t) => t.order_type === '23').length)
const sellCount = computed(() => _normalTrades.value.filter((t) => t.order_type === '24').length)
const buyAmount = computed(() =>
  _normalTrades.value.filter((t) => t.order_type === '23').reduce((s, t) => s + t.volume * t.price, 0)
)
const sellAmount = computed(() =>
  _normalTrades.value.filter((t) => t.order_type === '24').reduce((s, t) => s + t.volume * t.price, 0)
)

const filteredTrades = computed(() =>
  trades.value.filter((t) => {
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
  // 通过 holdings.refreshAll 重拉全量 RPC（统一日志）
  await holdingsStore.refreshAll()
}

function resetFilters() {
  filters.keyword = ''
  filters.order_type = ''
}

function exportCSV() {
  const header = ['交易日', '成交时间', '股票代码', '方向', '类型', '成交数量', '成交价格', '成交金额', '成交编号', '合同序号']
  const rows = filteredTrades.value.map((t) => [
    t.trd_date,
    t.trade_time,
    t.stock_code,
    t.order_type === '23' ? '买入' : (t.order_type === '24' ? '卖出' : t.order_type),
    Number(t.trade_type) === 1 ? '撤单' : '成交',
    t.volume,
    t.price,
    (t.volume * t.price).toFixed(2),
    t.trade_id,
    t.order_id
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `成交查询_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

// 页面挂载不再 fetch — 数据从 holdings 缓存读
</script>

<style scoped>
.trades-view {
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
  justify-content: space-between;
  align-items: center;
}

.pill-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.pill-value {
  font-size: 17px;
  font-weight: 700;
}

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
