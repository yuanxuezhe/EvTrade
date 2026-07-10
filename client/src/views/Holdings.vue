<template>
  <div class="holdings-view fade-in-up">
    <!-- 筛选 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索股票代码或名称"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
        />
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
        <el-button :icon="Download" @click="exportCSV" :disabled="filteredPositions.length === 0">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table :data="pagedPositions" v-loading="loading" style="width: 100%">
        <el-table-column prop="stock_code" label="股票代码" width="120">
          <template #default="{ row }">
            <span class="stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_vol" label="期初持仓" align="right" min-width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol" label="持仓量" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avl_vol" label="可用" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cost_price" label="成本价" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.cost_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最新价" align="right" width="140" :key="quoteTick">
          <template #default="{ row }">
            <span
              v-if="getLastPrice(row.stock_code) != null"
              class="text-mono"
              :class="priceClass(row)"
            >
              {{ formatMoneyExact(getLastPrice(row.stock_code)) }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="市值" align="right" width="140" :key="'mv' + quoteTick">
          <template #default="{ row }">
            <span v-if="getMarketValue(row) != null" class="text-mono">
              {{ formatMoney(getMarketValue(row)) }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="浮动盈亏" align="right" width="140" :key="'pl' + quoteTick">
          <template #default="{ row }">
            <template v-if="getProfit(row) != null">
              <span class="text-mono" :class="profitClass(getProfit(row))">
                {{ formatMoney(getProfit(row)) }}
              </span>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="收益率" align="right" width="120" :key="'rt' + quoteTick">
          <template #default="{ row }">
            <template v-if="getReturnRate(row) != null">
              <span class="text-mono" :class="profitClass(getReturnRate(row))">
                {{ formatPercent(getReturnRate(row)) }}
              </span>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无持仓" :image-size="100" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredPositions.length"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import { api } from '../api'
import { formatNumber, formatMoney } from '../utils/format'
import { useQuoteStore } from '../stores/quote'
import { useHoldingsStore } from '../stores/holdings'

/**
 * 持仓数据来源：holdings store（App 启动时已 bootstrap）
 * 行情来源：quote store（由 holdings store 白名单控制 — 仅持仓代码入）
 * 实时市值/盈亏/收益率：holdings store 的 computed
 *
 * 2026-07-09 quote-snapshot-subscribe:
 *   - 持仓 code 列表变化时, 自动 subscribe/unsubscribe 行情
 *   - watch positionCodes.value → diff → quoteStore.subscribe(new) / unsubscribe(removed)
 *   - 页面卸载时 unsubscribe 全部（避免幽灵订阅）
 */

// 从 holdings store 读 positions — 用 computed proxy
const holdingsStore = useHoldingsStore()
const quoteStore = useQuoteStore()
const positions = computed({
  get: () => holdingsStore.positions,
  set: (v) => { holdingsStore.positions = v }   // 兼容老写法
})
const loading = computed(() => holdingsStore.loading)

const page = ref(1)
const pageSize = ref(20)

const filters = reactive({ keyword: '' })

// 用一个 ref 强制 column 在 quote 更新时刷新 — Vue 对 Map.set 内部值的更新
// 不能精确追踪到每行，但每次推送都 ++tick 让模板重读 getter 即可触发响应
const quoteTick = ref(0)
let _quoteTimer = null

const filteredPositions = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  if (!kw) return positions.value
  return positions.value.filter(
    (p) => (p.stock_code || '').toLowerCase().includes(kw)
  )
})

const pagedPositions = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredPositions.value.slice(start, start + pageSize.value)
})

// ---- 行情查询（代理 holdings store；holdings 内部 watch quote 自动重算） ----

function getLastPrice(code) {
  return holdingsStore.getLivePrice(code)
}

function getMarketValue(row) {
  return holdingsStore.getMarketValue(row)
}

function getProfit(row) {
  return holdingsStore.getProfit(row)
}

function getReturnRate(row) {
  return holdingsStore.getReturnRate(row)
}

function profitClass(v) {
  if (v == null) return ''
  if (v > 0) return 'text-up'    // 正: 红
  if (v < 0) return 'text-down'  // 负: 绿
  return 'text-flat'             // 平: 黑
}

function priceClass(row) {
  // 2026-07-10: 按"最新价 vs 昨收价"着色（中国市场红涨绿跌）
  const price = getLastPrice(row.stock_code)
  if (price == null) return ''
  const q = quoteStore.byCode.get(row.stock_code)
  const prev = q?.prev_close != null ? Number(q.prev_close) : null
  if (prev == null || prev === 0) return ''
  if (price > prev) return 'text-up'    // 红
  if (price < prev) return 'text-down'  // 绿
  return 'text-flat'                    // 黑
}

function formatMoneyExact(v) {
  // 价格按行情原始数据原样输出，不截断、不补 0
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  // String(num) 保留 IEEE 754 的最短表示，自然就是原始精度
  return String(n)
}

function formatPercent(v) {
  if (v == null || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(2)}%`
}

// ---- 行情 tick：每 1s 强制一次刷新（聚合刷新避免抖动） ------------------

function startQuoteTick() {
  if (_quoteTimer) return
  _quoteTimer = setInterval(() => {
    if (quoteStore.size > 0) quoteTick.value++
  }, 1000)
}

function stopQuoteTick() {
  if (_quoteTimer) {
    clearInterval(_quoteTimer)
    _quoteTimer = null
  }
}

// ---- 数据加载 -----------------------------------------------------------

async function refresh() {
  // 委托给 holdings store（共享缓存 + 触发 ws subscribe）
  await holdingsStore.refreshPositions()
}

function resetFilters() {
  filters.keyword = ''
}

function exportCSV() {
  const header = [
    '股票代码', '期初持仓', '持仓量', '可用', '成本价',
    '最新价', '市值', '浮动盈亏', '收益率'
  ]
  const rows = filteredPositions.value.map((p) => {
    const price = getLastPrice(p.stock_code)
    const mv = getMarketValue(p)
    const profit = getProfit(p)
    const rate = getReturnRate(p)
    return [
      p.stock_code,
      p.last_vol,
      p.vol,
      p.avl_vol,
      p.cost_price,
      price != null ? String(price) : '',
      mv != null ? mv.toFixed(2) : '',
      profit != null ? profit.toFixed(2) : '',
      rate != null ? (rate * 100).toFixed(2) + '%' : ''
    ]
  })
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `持仓查询_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

onMounted(() => {
  // holdings store 在 App.vue 启动时已 bootstrap；这里只兜底
  if (!holdingsStore.bootstrapped) {
    holdingsStore.bootstrap()
  }
  startQuoteTick()
  // 2026-07-09 quote-snapshot-subscribe: 持仓 codes 变化时自动调订阅
  _lastSubscribedCodes = new Set(holdingsStore.positionCodes || [])
  if (_lastSubscribedCodes.size > 0) {
    quoteStore.subscribe(Array.from(_lastSubscribedCodes))
  }
})

// 2026-07-09 quote-snapshot-subscribe: 持仓 code 列表 diff → 增量订阅
let _lastSubscribedCodes = new Set()
watch(
  () => holdingsStore.positionCodes,
  (newCodes, oldCodes) => {
    const newSet = new Set(newCodes || [])
    const oldSet = new Set(oldCodes || _lastSubscribedCodes)
    const toAdd = [...newSet].filter(c => !oldSet.has(c))
    const toRemove = [...oldSet].filter(c => !newSet.has(c))
    if (toAdd.length > 0) {
      quoteStore.subscribe(toAdd)
    }
    if (toRemove.length > 0) {
      quoteStore.unsubscribe(toRemove)
    }
    _lastSubscribedCodes = newSet
  },
  { flush: 'post' }  // 等 DOM 更新后跑，避免和 holdings computed 抢资源
)

onBeforeUnmount(() => {
  stopQuoteTick()
  // 2026-07-09 quote-snapshot-subscribe: 页面卸载时取消本页面持有的订阅
  if (_lastSubscribedCodes.size > 0) {
    quoteStore.unsubscribe(Array.from(_lastSubscribedCodes))
    _lastSubscribedCodes = new Set()
  }
})
</script>

<style scoped>
.holdings-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
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

.text-mono {
  font-family: var(--font-mono);
}

.text-muted {
  color: var(--text-placeholder);
  font-family: var(--font-mono);
}

.text-up {
  color: var(--color-up);
  font-weight: 600;
}

.text-down {
  color: var(--color-down);
  font-weight: 600;
}

.text-flat {
  color: var(--text-primary);
  font-weight: 600;
}

.pagination {
  padding: var(--space-3) var(--space-4);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--border-light);
}
</style>