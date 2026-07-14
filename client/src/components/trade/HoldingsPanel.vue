<!--
  HoldingsPanel.vue — 持仓 mini 面板 (v30 Trade.vue 5 区重构: 嵌入右栏 flex:2; v31.1 字段补全 + 列宽调优; v32 名称查 stocks cache)

  数据源: useHoldingsStore().positions (App.vue 启动时已 bootstrap)
  行情:   useQuoteStore() (持仓 codes 已自动 subscribe,见 holdings store)
  实时:   1s tick 强制 column 重读 getter,响应 quote 更新

  v32 修订:
    - 证券名称列从 row.stock_name (后端字段) 改为 stockName(row.stock_code) (查 stocks store 缓存)
    - 后端不再返回 name,前端统一查 stocks cache 补名称,查不到显式 '—'

  精简相对 Holdings.vue:
    - 无 filter-bar (迷你 el-input 内嵌到 .tp-header)
    - 无 pagination (mini panel 不分页,只显示前 ~30 行,溢出滚动)
    - 无 export 按钮 (完整导出走 /holdings 全页)
    - 保留: 实时行情 + 市值/盈亏/收益率计算 + 红涨绿跌配色

  列 (v31.1 字段与 Holdings.vue 全页对齐, 共 10 列, 紧凑列宽:
    代码 76 (fixed left) / 名称 64 / 期初 64 / 持仓 64 / 可用 64 / 成本 68 /
    最新 68 / 市值 80 / 浮盈 90 / 收益 80 (fixed right) → 总宽 ~718
    适配窄列右栏 (~856px viewport): 10 列全 fit, 横向滚动由 el-table 默认处理)
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

    <div class="tp-body">
      <el-table
        :data="pagedPositions"
        :show-overflow-tooltip="true"
        stripe
        size="small"
        class="tp-table"
        :key="quoteTick"
      >
        <!-- v31.1: 10 列布局, 列宽压缩适应窄列 mini panel (目标总宽 ~720px fit 856 viewport) -->
        <el-table-column prop="stock_code" label="代码" width="76" fixed="left">
          <template #default="{ row }">
            <span class="tp-stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_name" label="名称" width="64" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-secondary">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_vol" label="期初" align="right" width="64">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol" label="持仓" align="right" width="64">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avl_vol" label="可用" align="right" width="64">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cost_price" label="成本" align="right" width="68">
          <template #default="{ row }">
            <span class="text-mono">{{ row.cost_price != null ? formatMoney(row.cost_price) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最新" align="right" width="68">
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
        <el-table-column label="市值" align="right" width="80">
          <template #default="{ row }">
            <span v-if="getMarketValue(row) != null" class="text-mono">
              {{ formatMoney(getMarketValue(row)) }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="浮动盈亏" align="right" width="90">
          <template #default="{ row }">
            <template v-if="getProfit(row) != null">
              <span class="text-mono" :class="profitClass(getProfit(row))">
                {{ formatMoney(getProfit(row)) }}
              </span>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="收益率" align="right" width="80" fixed="right">
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
          <el-empty description="暂无持仓" :image-size="80" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { formatNumber, formatMoney } from '../../utils/format'
import { stockName } from '../../utils/stockNames'
import { useQuoteStore } from '../../stores/quote'
import { useHoldingsStore } from '../../stores/holdings'

const holdingsStore = useHoldingsStore()
const quoteStore = useQuoteStore()

// 持仓 codes 走 store (App.vue 已 bootstrap + 自动订阅行情)
// 这里不需要自己 bootstrap / subscribe — store 单例共享
const positions = computed(() => holdingsStore.positions || [])

// 1s tick: 强制 column 重读 getter (quote push 不精确触发响应)
const quoteTick = ref(0)
let _timer = null

function startTick() {
  if (_timer) return
  _timer = setInterval(() => {
    if (quoteStore.size > 0) quoteTick.value++
  }, 1000)
}
function stopTick() {
  if (_timer) {
    clearInterval(_timer)
    _timer = null
  }
}

// 关键字过滤 (迷你 filter, 只匹配代码 + 名称)
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

// mini panel 不分页,但 el-table 不分页大数据会卡, 取前 30 行够用
const pagedPositions = computed(() => filteredPositions.value.slice(0, 30))

// 总市值
const totalMv = computed(() => {
  let sum = 0
  for (const p of filteredPositions.value) {
    const mv = holdingsStore.getMarketValue(p)
    if (mv != null) sum += mv
  }
  return sum
})

// ---- 行情查询 ------------------------------------------------------

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
  const q = quoteStore.byCode.get(row.stock_code)
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

onMounted(() => startTick())
onBeforeUnmount(() => stopTick())
</script>

<style scoped>
/* 复用 TodayOrdersPanel/TodayTradesPanel 的 .tp-* 类 (Trade.vue 内 trade-panels-col 已覆盖) */
.hp-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
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
</style>
