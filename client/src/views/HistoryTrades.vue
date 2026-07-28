<!--
  HistoryTrades.vue — 历史成交通视图（v12 + v13 预设 chip + 强制历史范围）

  数据源：api.getTrades({ startDate, endDate, stockCode }) 局部查询
  不走 Pinia（历史数据非"实时"语义）
  不入 IDB（页面切换后下次进来重新拉）

  v13 修订: 同 HistoryOrders.vue — 加 4 个预设 chip, picker 禁 today+, onMounted 留空
-->
<template>
  <div class="history-trades-view fade-in-up">
    <!-- 查询条件 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <!-- 预设日期 chip (历史区间, 不含今日) -->
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
      <el-table
        :data="pagedResults"
        style="width: 100%"
        :default-sort="{ prop: 'trade_time', order: 'descending' }"
      >
        <!-- v72: 10 列走 COL 常量 -->
        <el-table-column prop="trd_date" label="交易日" sortable v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="标的" show-overflow-tooltip v-bind="COL.STOCK_TARGET">
          <template #default="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_type" label="方向" v-bind="COL.DIRECTION">
          <template #default="{ row }">
            <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">成交</span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="成交数量" sortable v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="成交价格" sortable v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成交金额" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">¥{{ formatMoney(localAmount(row)) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_id" label="成交编号" show-overflow-tooltip v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_time" label="成交时间" sortable v-bind="COL.TIME">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_time }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="hasQueried ? '该区间内无成交记录' : '请选择起止日期查询'"
            :image-size="100"
          />
        </template>
      </el-table>

      <div class="pagination" v-if="hasQueried">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="results.length"
          :page-sizes="[10, 20, 50, 100, 500]"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import { api } from '../api'
import { formatMoney, formatNumber } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import { shiftDateStr } from '../utils/date'

/**
 * 历史成交通视图（v12 + v13 trade-page-redesign-v2）
 *
 * 数据契约: 同 HistoryOrders (v13 修订: 加 4 chip, picker 禁 today+, onMounted 留空)
 */
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

const page = ref(1)
const pageSize = ref(20)

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

const pagedResults = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return results.value.slice(start, start + pageSize.value)
})

// chip ↔ picker 双向联动高亮
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
    // v113: 改走 holdingsStore.trades 全量缓存 + 前端 trd_date 区间过滤
    //   不再独立 RPC 拉 (与 startup cache 一致, 统一单一可信源)
    const opts = { startDate, endDate }
    if (stockCode.value) opts.stockCode = stockCode.value
    const all = holdingsStore.trades || []
    const inRange = all.filter((t) => {
      const td = String(t.trd_date || '')
      if (td < startDate || td > endDate) return false
      if (opts.stockCode && t.stock_code !== opts.stockCode) return false
      return true
    })
    results.value = inRange
    hasQueried.value = true
    page.value = 1
  } catch (e) {
    results.value = []
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
  // 本地算 price × volume（与后端 trd_cfm amount 公式一致）
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

function exportCSV() {
  const header = ['交易日', '成交时间', '股票代码', '方向', '类型',
                  '成交数量', '成交价格', '成交金额', '成交编号']
  const rows = results.value.map((t) => [
    t.trd_date,
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
  link.download = `历史成交_${queryLabel.value}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

// v13: onMounted 留空 (无默认查询, 用户主动选 chip 或 picker)
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

/* v13: 预设日期 chip (历史区间, 不含今日) */
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

.pagination {
  padding: var(--space-3) var(--space-4);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--border-light);
}

@media (max-width: 1100px) {
  .stats-row { grid-template-columns: 1fr; }
}
</style>