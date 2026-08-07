<!--
  HistoryTrades.vue — 历史成交通视图 (统一 DataTableView)

  数据源（v114）：前端 IDB 全量缓存 + trd_date 区间过滤
  v13：预设 chip + picker 禁 today+ + onMounted 留空
-->
<template>
  <div class="history-trades-view fade-in-up">
    <!-- 查询条件 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <div class="filter-chips">
          <button
            v-for="(preset, idx) in PRESETS"
            :key="preset.label"
            type="button"
            class="filter-chip"
            :class="{ active: activePreset === idx }"
            :title="preset.tooltip"
            @click="setPreset(preset)"
          >
            {{ preset.label }}
          </button>
        </div>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="→"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYYMMDD"
          format="YYYY-MM-DD"
          :clearable="true"
          :editable="false"
          :disabled-date="isAfterToday"
          style="width: 280px"
        />
        <el-input
          v-model="stockCode"
          placeholder="股票代码 (可选)"
          clearable
          style="width: 200px"
        />
        <el-button type="primary" :icon="Search" :loading="loading"
                   :disabled="!isDateRangeValid" @click="runQuery">
          查询
        </el-button>
        <el-button :icon="Refresh" @click="resetQuery">重置</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Download" :disabled="results.length === 0" @click="exportCSV">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 校验提示 -->
    <el-alert v-if="dateRange && !isDateRangeValid"
              title="开始日期不能晚于结束日期"
              type="warning" :closable="false" show-icon />

    <!-- 概览 -->
    <section class="stats-row" v-if="hasQueried">
      <div class="stat-pill">
        <div class="pill-label">查询区间</div>
        <div class="pill-value text-mono">{{ queryLabel }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">成交笔数</div>
        <div class="pill-value text-mono">{{ results.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">股票过滤</div>
        <div class="pill-value text-mono">{{ stockCode || '全部' }}</div>
      </div>
    </section>

    <!-- 表格 -->
    <div class="content-card" v-loading="loading">
      <DataTableView
        v-if="hasQueried"
        :columns="tradeColumns"
        :data="results"
        :default-sort="{ prop: 'trade_time', order: 'descending' }"
        :empty-description="'该区间内无成交记录'"
      >
        <template #column-trd_date="{ row }">
          <span class="text-mono text-secondary">{{ row.trd_date }}</span>
        </template>
        <template #column-stock_code="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
          <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
        </template>
        <template #column-direction="{ row }">
          <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
            {{ row.order_type === '23' ? '买入' : '卖出' }}
          </span>
        </template>
        <template #column-type="{ row }">
          <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
          <span v-else class="text-secondary">成交</span>
        </template>
        <template #column-volume="{ row }">
          <span class="text-mono">{{ formatNumber(row.volume) }}</span>
        </template>
        <template #column-price="{ row }">
          <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
        </template>
        <template #column-amount="{ row }">
          <span class="text-mono">¥{{ formatMoney(localAmount(row)) }}</span>
        </template>
        <template #column-trade_id="{ row }">
          <span class="text-mono text-secondary">{{ row.trade_id }}</span>
        </template>
        <template #column-trade_time="{ row }">
          <span class="text-mono text-secondary">{{ row.trade_time }}</span>
        </template>
      </DataTableView>
      <el-empty v-else description="请选择起止日期查询" :image-size="100" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import DataTableView from '../components/DataTableView.vue'
import { formatMoney, formatNumber } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import { shiftDateStr } from '../utils/date'
import { loadAllTrades } from '../stores/holdings_idb'

const PRESETS = [
  { label: '昨日',     startOffset: -1,  endOffset: -1,  tooltip: '查询昨天 1 天（不含今日）' },
  { label: '最近三天', startOffset: -3,  endOffset: -1,  tooltip: '查询 today-3 ~ today-1, 不含今日' },
  { label: '最近一周', startOffset: -7,  endOffset: -1,  tooltip: '查询 today-7 ~ today-1, 不含今日' },
  { label: '最近一个月', startOffset: -30, endOffset: -1, tooltip: '查询 today-30 ~ today-1, 不含今日' }
]

function todayYYYYMMDD() {
  const dt = new Date()
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const d = String(dt.getDate()).padStart(2, '0')
  return `${y}${m}${d}`
}

function isAfterToday(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}${m}${d}` >= todayYYYYMMDD()
}

function presetRange(preset) {
  const today = todayYYYYMMDD()
  return [shiftDateStr(today, preset.startOffset), shiftDateStr(today, preset.endOffset)]
}

const dateRange = ref(null)
const stockCode = ref('')
const results = ref([])
const loading = ref(false)
const hasQueried = ref(false)

const isDateRangeValid = computed(() => {
  if (!dateRange.value || dateRange.value.length !== 2) return false
  const [s, e] = dateRange.value
  return s && e && s <= e
})

const queryLabel = computed(() => {
  if (!dateRange.value || dateRange.value.length !== 2) return '-'
  const [s, e] = dateRange.value
  if (s === e) return s
  return `${s} ~ ${e}`
})

const activePreset = computed(() => {
  if (!isDateRangeValid.value) return -1
  const [curS, curE] = dateRange.value
  return PRESETS.findIndex((p) => {
    const [s, e] = presetRange(p)
    return curS === s && curE === e
  })
})

async function runQuery() {
  if (!isDateRangeValid.value) return
  const [startDate, endDate] = dateRange.value
  loading.value = true
  try {
    const all = (await loadAllTrades()) || []
    const stockCodeFilter = stockCode.value || ''
    const inRange = all.filter((t) => {
      const td = String(t.trd_date || '')
      if (td < startDate || td > endDate) return false
      if (stockCodeFilter && t.stock_code !== stockCodeFilter) return false
      return true
    })
    results.value = inRange
    hasQueried.value = true
  } catch (e) {
    results.value = []
    console.error('[HistoryTrades] IDB 查询失败:', e?.message || e)
  } finally {
    loading.value = false
  }
}

async function setPreset(preset) {
  dateRange.value = presetRange(preset)
  await runQuery()
}

function resetQuery() {
  dateRange.value = null
  stockCode.value = ''
  results.value = []
  hasQueried.value = false
}

function localAmount(t) {
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

function exportCSV() {
  const header = ['交易日', '成交时间', '股票代码', '方向', '类型',
                  '成交数量', '成交价格', '成交金额', '成交编号']
  const rows = results.value.map((t) => [
    t.trd_date, t.trade_time, t.stock_code,
    t.order_type === '23' ? '买入' : (t.order_type === '24' ? '卖出' : t.order_type),
    Number(t.trade_type) === 1 ? '撤单' : '成交',
    t.volume, t.price, localAmount(t).toFixed(2), t.trade_id
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `历史成交_${queryLabel.value}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

const tradeColumns = [
  { key: 'trd_date', label: '交易日', vBind: COL.STOCK_CODE },
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'direction', label: '方向', vBind: COL.DIRECTION, sortable: false },
  { key: 'type', label: '类型', width: 100, sortable: false },
  { key: 'volume', label: '成交数量', vBind: COL.NUMBER },
  { key: 'price', label: '成交价格', vBind: COL.MONEY },
  { key: 'amount', label: '成交金额', vBind: COL.MONEY, sortable: false },
  { key: 'trade_id', label: '成交编号', vBind: COL.STOCK_CODE },
  { key: 'trade_time', label: '成交时间', vBind: COL.TIME },
]
</script>

<style scoped>
.history-trades-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
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
  align-items: center;
}
.filter-right { display: flex; gap: var(--space-2); }

.filter-chips {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  align-items: center;
}
.filter-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 14px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-base);
  background: var(--bg-elevated);
  color: var(--text-regular);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}
.filter-chip:hover {
  border-color: var(--brand-primary);
  color: var(--brand-primary);
}
.filter-chip.active {
  background: var(--brand-primary);
  color: white;
  border-color: var(--brand-primary);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
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
.pill-value { font-size: 16px; font-weight: 700; }

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

.tp-stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
}

@media (max-width: 1100px) {
  .stats-row { grid-template-columns: 1fr; }
}
</style>
