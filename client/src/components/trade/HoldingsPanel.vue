<!--
  HoldingsPanel.vue — 持仓 mini 面板 (统一 DataTableView)

  数据源: useHoldingsStore().positions
  行情:   useQuoteStore()
  v55: select-stock emit (单击), apply-to-order emit (双击)
-->
<template>
  <div class="hp-shell content-card">
    <div class="tp-header">
      <h3 class="tp-title">持仓</h3>
      <span class="hp-count text-mono">
        {{ filteredPositions.length }} 只 / 持仓 {{ formatMoney(totalMv) }}
      </span>
      <el-input
        v-model="keyword"
        placeholder="代码过滤"
        clearable
        size="small"
        class="hp-filter"
      />
    </div>

    <div class="tp-body" v-if="idbSyncStatus?.positions !== 'syncing'">
      <DataTableView
        :columns="holdingsColumns"
        :data="filteredPositions"
        :cell-class-name="cellClassName"
        :empty-description="'暂无持仓'"
        @row-click="onRowClick"
        @row-dblclick="onRowDblclick"
        class="hp-data-table"
      >
        <template #column-stock_code="{ row }">
          <span class="tp-stock-code">{{ row.stock_code }}</span>
          <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
        </template>

        <template #column-last_vol="{ row }">
          <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
        </template>

        <template #column-vol="{ row }">
          <span class="text-mono">{{ formatNumber(row.vol) }}</span>
        </template>

        <template #column-avl_vol="{ row }">
          <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
        </template>

        <template #column-cost_price="{ row }">
          <span class="text-mono">{{ row.cost_price != null ? formatPrice(row.cost_price, row.stock_code) : '—' }}</span>
        </template>

        <template #column-last_price="{ row }">
          <span v-if="getLastPrice(row.stock_code) != null" class="text-mono" :class="priceClass(row)">
            {{ formatMoneyExact(getLastPrice(row.stock_code)) }}
          </span>
          <span v-else class="text-muted">—</span>
        </template>

        <template #column-market_value="{ row }">
          <span v-if="getMarketValue(row) != null" class="text-mono">
            {{ formatMoney(getMarketValue(row)) }}
          </span>
          <span v-else class="text-muted">—</span>
        </template>

        <template #column-profit="{ row }">
          <template v-if="getProfit(row) != null">
            <span class="text-mono" :class="profitClass(getProfit(row))">
              {{ formatMoney(getProfit(row)) }}
            </span>
          </template>
          <span v-else class="text-muted">—</span>
        </template>

        <template #column-return_rate="{ row }">
          <template v-if="getReturnRate(row) != null">
            <span class="text-mono" :class="profitClass(getReturnRate(row))">
              {{ formatPercent(getReturnRate(row)) }}
            </span>
          </template>
          <span v-else class="text-muted">—</span>
        </template>
      </DataTableView>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import DataTableView from '../DataTableView.vue'
import { formatNumber, formatMoney } from '../../utils/format'
import { formatPrice } from '../../composables/usePricePrecision'
import { stockName } from '../../utils/stockNames'
import { COL } from '../../utils/tableColumns'
import { useQuoteStore } from '../../stores/quote'
import { useHoldingsStore } from '../../stores/holdings'

const holdingsStore = useHoldingsStore()
const quoteStore = useQuoteStore()

// v55: click → select-stock, dblclick → apply-to-order
const emit = defineEmits(['apply-to-order', 'select-stock'])
let lastDblclickTs = 0
function onRowDblclick(row) {
  if (!row || !row.stock_code) return
  const name = stockName(row.stock_code) || row.stock_name || ''
  emit('apply-to-order', { stock_code: row.stock_code, stock_name: name })
  lastDblclickTs = Date.now()
}
function onRowClick(row) {
  if (!row || !row.stock_code) return
  if (Date.now() - lastDblclickTs < 300) return
  const name = stockName(row.stock_code) || row.stock_name || ''
  emit('select-stock', { stock_code: row.stock_code, stock_name: name })
}

const positions = computed(() => holdingsStore.positions || [])
const idbSyncStatus = computed(() => holdingsStore.idbSyncStatus || {})

// 关键字过滤
const keyword = ref('')
const filteredPositions = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return positions.value
  return positions.value.filter((p) => {
    const code = (p.stock_code || '').toLowerCase()
    const name = (stockName(p.stock_code) || '').toLowerCase()
    return code.includes(kw) || name.includes(kw)
  })
})

// 总市值
const totalMv = computed(() => {
  let sum = 0
  for (const p of filteredPositions.value) {
    const mv = holdingsStore.getMarketValue(p)
    if (mv != null) sum += mv
  }
  return sum
})

// 行情 trigger
const quoteTickTrigger = computed(() => quoteStore.size || 0)

// v37 移动端列标签
function cellClassName({ row, column }) {
  const label = (column && column.label) || ''
  return 'col-' + label
}

function getLastPrice(code) {
  void quoteTickTrigger.value
  return holdingsStore.getLivePrice(code)
}
function getMarketValue(row) {
  void quoteTickTrigger.value
  return holdingsStore.getMarketValue(row)
}
function getProfit(row) {
  void quoteTickTrigger.value
  return holdingsStore.getProfit(row)
}
function getReturnRate(row) {
  void quoteTickTrigger.value
  return holdingsStore.getReturnRate ? holdingsStore.getReturnRate(row) : null
}

function profitClass(v) {
  if (v == null) return ''
  if (v > 0) return 'text-up'
  if (v < 0) return 'text-down'
  return 'text-flat'
}
function priceClass(row) {
  const price = getLastPrice(row.stock_code)
  if (price == null) return ''
  const q = quoteStore.get(row.stock_code) || null
  const prev = q?.prev_close != null ? Number(q.prev_close) : null
  if (prev == null || prev === 0) return ''
  if (price > prev) return 'text-up'
  if (price < prev) return 'text-down'
  return 'text-flat'
}

function formatMoneyExact(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return String(n)
}

function formatPercent(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${(n * 100).toFixed(2)}%`
}

// 列定义
const holdingsColumns = [
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'last_vol', label: '期初', vBind: COL.NUMBER },
  { key: 'vol', label: '持仓', vBind: COL.NUMBER },
  { key: 'avl_vol', label: '可用', vBind: COL.NUMBER },
  { key: 'cost_price', label: '成本', vBind: COL.MONEY },
  { key: 'last_price', label: '最新', vBind: COL.MONEY },
  { key: 'market_value', label: '市值', vBind: COL.MONEY, sortable: false },
  { key: 'profit', label: '浮动盈亏', vBind: COL.MONEY, sortable: false },
  { key: 'return_rate', label: '收益率', fixed: 'right', vBind: COL.NUMBER, sortable: false },
]
</script>

<style scoped>
.hp-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.tp-header {
  display: flex;
  align-items: center;
  padding: var(--space-3, 8px) var(--space-4, 12px);
  border-bottom: 1px solid var(--border-light, #ebeef5);
  flex-shrink: 0;
}

.tp-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}

.tp-body {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

:deep(.el-table__row) {
  cursor: pointer;
}
:deep(.el-table__row:hover > td.el-table__cell) {
  background-color: var(--bg-hover) !important;
}

.hp-count {
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  margin-left: 8px;
  flex-shrink: 0;
}
.hp-filter {
  width: 140px;
  margin-left: auto;
  flex-shrink: 0;
}
:deep(.hp-filter .el-input__wrapper) {
  padding: 1px 8px;
}
:deep(.hp-filter .el-input__inner) {
  height: 24px;
  font-size: 12px;
}

.tp-stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
}

.text-muted {
  color: var(--el-text-color-placeholder, #c0c4cc);
}
</style>
