<!--
  CacheTrades.vue — 缓存成交查看 (IDB 读取, 调试用)

  数据源: IDB (loadAllTrades), onMounted 自动加载全部
  查询条件为可选过滤器, DataTableView 内部分页
-->
<template>
  <div class="cache-trades-view fade-in-up" :style="rootStyle">
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
        <el-button :icon="Refresh" @click="resetQuery">重置</el-button>
      </div>
    </div>

    <el-alert v-if="dateRange && !isDateRangeValid"
              title="开始日期不能晚于结束日期"
              type="warning" :closable="false" show-icon />

    <!-- 表格 -->
    <div class="content-card table-wrap" v-loading="loading">
      <DataTableView
        :columns="tradeColumns"
        :data="results"
        :default-sort="{ prop: 'trade_time', order: 'descending' }"
        :default-page-size="50"
        :empty-description="'无成交记录'"
        @row-dblclick="(row) => { if (row.stock_code) stockCode = row.stock_code }"
      >
        <template #column-trd_date="{ row }">
          <span class="text-mono text-secondary">{{ row.trd_date }}</span>
        </template>
        <template #column-order_no="{ row }">
          <span class="text-mono text-secondary">{{ row.order_no }}</span>
        </template>
        <template #column-type="{ row }">
          <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
          <span v-else class="text-secondary">成交</span>
        </template>
        <template #column-stock_code="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
          <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
        </template>
        <template #column-direction="{ row }">
          <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
            {{ row.order_type === '23' ? '买' : '卖' }}
          </span>
        </template>
        <template #column-volume="{ row }">
          <span class="text-mono">{{ formatNumber(row.volume) }}</span>
        </template>
        <template #column-price="{ row }">
          <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
        </template>
        <template #column-amount="{ row }">
          <span class="text-mono">{{ formatMoney(row.amount) }}</span>
        </template>
        <template #column-trade_id="{ row }">
          <span class="text-mono text-secondary">{{ row.trade_id }}</span>
        </template>
        <template #column-trade_time="{ row }">
          <span class="text-mono text-secondary">{{ row.trade_time }}</span>
        </template>
      </DataTableView>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import DataTableView from '../components/DataTableView.vue'
import { formatMoney, formatNumber } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import { shiftDateStr } from '../utils/date'
import { loadAllTrades } from '../stores/holdings_idb'
import { useUiStore } from '../stores/ui'
const uiStore = useUiStore()

const PRESETS = [
  { label: '当日',     startOffset: 0, endOffset: 0, tooltip: '查询今天' },
  { label: '昨日',     startOffset: -1,  endOffset: -1,  tooltip: '查询昨天 1 天（不含今日）' },
  { label: '最近三天', startOffset: -3,  endOffset: -1,  tooltip: '查询 today-3 ~ today-1, 不含今日' },
  { label: '最近一周', startOffset: -7,  endOffset: -1,  tooltip: '查询 today-7 ~ today-1, 不含今日' },
  { label: '最近一个月', startOffset: -30, endOffset: -1, tooltip: '查询 today-30 ~ today-1, 不含今日' }
]

function todayYYYYMMDD() {
  const dt = new Date()
  return `${dt.getFullYear()}${String(dt.getMonth() + 1).padStart(2, '0')}${String(dt.getDate()).padStart(2, '0')}`
}
function isAfterToday(d) { return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}` > todayYYYYMMDD() }
function presetRange(p) { const t = todayYYYYMMDD(); return [shiftDateStr(t, p.startOffset), shiftDateStr(t, p.endOffset)] }

const dateRange = ref(null)
const stockCode = ref('')
const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))
const allTrades = ref([])
const loading = ref(false)

const isDateRangeValid = computed(() => {
  if (!dateRange.value || dateRange.value.length !== 2) return false
  const [s, e] = dateRange.value; return s && e && s <= e
})
const queryLabel = computed(() => {
  if (!dateRange.value || dateRange.value.length !== 2) return '全部'
  const [s, e] = dateRange.value; return s === e ? s : `${s} ~ ${e}`
})
const activePreset = computed(() => {
  if (!isDateRangeValid.value) return -1
  const [curS, curE] = dateRange.value
  return PRESETS.findIndex((p) => { const [s, e] = presetRange(p); return curS === s && curE === e })
})

/** 过滤后的结果 */
const results = computed(() => {
  let filtered = allTrades.value
  if (dateRange.value && dateRange.value.length === 2 && isDateRangeValid.value) {
    const [startDate, endDate] = dateRange.value
    filtered = filtered.filter((t) => {
      const td = String(t.trd_date || '')
      return td >= startDate && td <= endDate
    })
  }
  if (stockCode.value) {
    const k = stockCode.value.trim().toLowerCase()
    filtered = filtered.filter((t) => String(t.stock_code || '').toLowerCase().includes(k))
  }
  return filtered
})

onMounted(async () => {
  loading.value = true
  try {
    allTrades.value = (await loadAllTrades()) || []
  } catch (e) { console.error('[CacheTrades] IDB 加载失败:', e?.message || e) }
  finally { loading.value = false }
})

function setPreset(p) { dateRange.value = presetRange(p) }
function resetQuery() { dateRange.value = null; stockCode.value = '' }

const tradeColumns = [
  { key: 'trd_date', label: '交易日', vBind: COL.TRD_DATE },
  { key: 'order_no', label: '委托编号', vBind: COL.SHORT_SNO },
  { key: 'type', label: '类型', width: 100, sortable: false },
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'direction', label: '方向', vBind: COL.DIRECTION, sortable: false },
  { key: 'volume', label: '成交量', vBind: COL.NUMBER },
  { key: 'price', label: '成交价', vBind: COL.PRICE },
  { key: 'amount', label: '金额', vBind: COL.MONEY, sortable: false },
  { key: 'trade_id', label: '成交编号', vBind: COL.LONG_SNO },
  { key: 'trade_time', label: '时间', vBind: COL.TIME },
]
</script>

<style scoped>
.cache-trades-view { display: flex; flex-direction: column; gap: var(--space-4); height: calc(100% - var(--oplog-extra, 0px)); min-height: 0; overflow: hidden; }
.filter-bar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-3) var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.filter-left { display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center; }
.filter-chips { display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center; }
.filter-chip { display: inline-flex; align-items: center; justify-content: center; padding: 6px 14px; border-radius: var(--radius-full); border: 1px solid var(--border-base); background: var(--bg-elevated); color: var(--text-regular); font-size: 13px; font-weight: 500; cursor: pointer; transition: all var(--transition-fast); white-space: nowrap; }
.filter-chip:hover { border-color: var(--brand-primary); color: var(--brand-primary); }
.filter-chip.active { background: var(--brand-primary); color: white; border-color: var(--brand-primary); }
.text-mono { font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace); }
.text-secondary { color: var(--text-secondary); }
.dir-chip { display: inline-flex; align-items: center; justify-content: center; padding: 2px 10px; border-radius: var(--radius-xs); font-size: 12px; font-weight: 600; }
.dir-chip.buy { background: var(--color-up-bg); color: var(--color-up); }
.dir-chip.sell { background: var(--color-down-bg); color: var(--color-down); }
.tp-stock-code { font-family: var(--font-mono); font-weight: 600; }
.table-wrap { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }
</style>
