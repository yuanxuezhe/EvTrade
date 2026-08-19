<!--
  StkPoolView.vue — 证券池只读查看 (stkpool-view-feature)

  定位: 仪表盘和交易下单之间插入的"自选"页签, 内容=证券池, 只读.
  与 StkPool.vue (完整 CRUD 管理页) 并存, 不互相影响.

  布局:
  - 顶部: el-select 下拉选池 + 池基本信息 (备注 + 标的数)
  - 主体: el-table 显示池内标的 + 实时行情 (最新价 / 涨跌幅 / 涨跌额 / 开盘 / 最高 / 最低 / 昨收 / 成交量)

  行情数据源: quote store (subscribe + ws push), watch tick 触发响应式更新.
  - >100 只自动订阅全市场 '' (quote.subscribe 内部判定)
  - 切换池时: 取消旧池订阅 + 订阅新池 codes

  行为契约:
  - onMounted 拉主表, 选第一条
  - watch(selectedPoolId) → 拉明细 + 重订行情订阅
  - onBeforeUnmount 取消订阅 (避免幽灵订阅)
  - race-condition guard: unmounted flag
-->
<template>
  <div class="stkpool-view-page">
    <!-- 顶部下拉 + 池信息 -->
    <header class="view-header">
      <div class="pool-picker">
        <span class="label">证券池:</span>
        <el-select
          v-model="selectedPoolId"
          placeholder="请选择证券池"
          style="width: 280px;"
          :loading="loadingPools"
          filterable
        >
          <el-option
            v-for="p in pools"
            :key="p.id"
            :label="p.name"
            :value="p.id"
          />
        </el-select>
        <span v-if="selectedPool" class="pool-meta">
          <el-tag size="small" type="info">{{ detail.length }} 只标的</el-tag>
          <span v-if="selectedPool.remark" class="remark">{{ selectedPool.remark }}</span>
        </span>
      </div>
      <div class="header-actions">
        <el-button size="small" :icon="Refresh" @click="refresh">刷新</el-button>
      </div>
    </header>

    <!-- 主体表格 -->
    <main class="view-main">
      <DataTableView
        v-if="selectedPoolId"
        :loading="loadingDetail"
        :columns="columns"
        :data="mergedData"
        row-key="stock_code"
        :empty-description="'该池暂无标的'"
        :highlight-current-row="false"
      >
        <template #column-stock_code="{ row }">
          <span class="detail-line">
            <span class="detail-code">{{ row.stock_code }}</span>
            <span class="detail-name">{{ getStockName(row.stock_code) }}</span>
          </span>
        </template>

        <template #column-last_price="{ row }">
            <span :class="formatPriceClass(row)">{{ formatPrice(row) }}</span>
        </template>
        <template #column-change_pct="{ row }">
            <span :class="formatChangeClass(row)">{{ formatChangePct(row) }}</span>
        </template>
        <template #column-change_amt="{ row }">
            <span :class="formatChangeClass(row)">{{ formatChangeAmt(row) }}</span>
        </template>
        <template #column-open_price="{ row }">
            {{ formatField(row, 'open_price') }}
        </template>
        <template #column-high_price="{ row }">
            {{ formatField(row, 'high_price') }}
        </template>
        <template #column-low_price="{ row }">
            {{ formatField(row, 'low_price') }}
        </template>
        <template #column-prev_close="{ row }">
            {{ formatField(row, 'prev_close') }}
        </template>
        <template #column-volume="{ row }">
            {{ formatVolume(row) }}
        </template>
        <template #column-amount="{ row }">
            {{ formatAmount(row) }}
        </template>
      </DataTableView>

      <el-empty v-else-if="!loadingPools && pools.length === 0" description="暂无证券池" />
      <el-empty v-else-if="!selectedPoolId" description="请选择证券池" />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { stkpoolApi } from '../api/stkpool'
import { useQuoteStore } from '../stores/quote'
import { useStocksStore } from '../stores/stocks'

import DataTableView from '../components/DataTableView.vue'

// ============ 列定义 ============
// 列定义用 prop=字段名 (不是 slot), 让 DataTableView 的 sortedData 能直接 sort(row[field])
// 行情字段通过 watch tick 的 mergedData 派生进 detail 行
// 自展示走 #column-${key} inline slot — 支持 A股红涨绿跌 (formatter 只能返字符串, 无法加 class)
const columns = [
  { key: 'stock_code', label: '标的', minWidth: 180, sortable: false },
  { key: 'last_price', label: '最新价', width: 100, align: 'right' },
  { key: 'change_pct', label: '涨跌幅', width: 100, align: 'right' },
  { key: 'change_amt', label: '涨跌额', width: 100, align: 'right' },
  { key: 'open_price', label: '开盘', width: 100, align: 'right' },
  { key: 'high_price', label: '最高', width: 100, align: 'right' },
  { key: 'low_price', label: '最低', width: 100, align: 'right' },
  { key: 'prev_close', label: '昨收', width: 100, align: 'right' },
  { key: 'volume', label: '成交量', width: 120, align: 'right' },
  { key: 'amount', label: '成交额', width: 140, align: 'right' },
]

// ============ 状态 ============
const pools = ref([])
const loadingPools = ref(false)
const selectedPoolId = ref(null)
const detail = ref([])
const loadingDetail = ref(false)

// store
const quoteStore = useQuoteStore()
const stocksStore = useStocksStore()

// 派生
const selectedPool = computed(
  () => pools.value.find(p => p.id === selectedPoolId.value) || null
)

// 当前池 codes (订阅用)
const detailCodes = computed(() => detail.value.map(d => d.stock_code))

// 合并行情字段进 detail 行 — 让 DataTableView 能 sort(row[field])
// 监听 quoteStore.tick 每次 ws push 后重算
// null 字段统一转为 undefined 保持 sort 行为一致 (null/undefined 排在最后)
const mergedData = computed(() => {
  const _ = quoteStore.tick  // 触发依赖
  return detail.value.map(d => {
    const q = quoteStore.get(d.stock_code) || {}
    const last = q.last_price ?? null
    const prev = q.prev_close ?? null
    const change_amt = (last != null && prev != null) ? (last - prev) : null
    const change_pct = (last != null && prev != null && prev !== 0)
      ? ((last - prev) / prev) * 100 : null
    return {
      ...d,
      last_price: last,
      change_pct,
      change_amt,
      open_price: q.open_price ?? null,
      high_price: q.high_price ?? null,
      low_price: q.low_price ?? null,
      prev_close: prev,
      volume: q.volume ?? null,
      amount: q.amount ?? null,
    }
  })
})

// race-condition guard
let unmounted = false
onBeforeUnmount(() => {
  unmounted = true
  // 取消订阅避免幽灵订阅
  if (detailCodes.value.length > 0) {
    quoteStore.unsubscribe(detailCodes.value)
  }
})

// ============ 数据加载 ============
function getStockName(code) {
  return stocksStore.stockName(code) || code
}

async function loadPools() {
  loadingPools.value = true
  try {
    const rows = await stkpoolApi.list()
    if (unmounted) return
    pools.value = rows
    if (!selectedPoolId.value && rows.length > 0) {
      selectedPoolId.value = rows[0].id
    }
  } catch (err) {
    if (unmounted) return
    ElMessage.error('加载池列表失败: ' + extractErrorMsg(err))
  } finally {
    if (!unmounted) loadingPools.value = false
  }
}

async function loadDetail(poolId) {
  loadingDetail.value = true
  try {
    const rows = await stkpoolApi.detail(poolId)
    if (unmounted) return
    detail.value = rows
    // 订阅行情
    const codes = rows.map(r => r.stock_code)
    if (codes.length > 0) {
      quoteStore.subscribe(codes)
    }
  } catch (err) {
    if (unmounted) return
    ElMessage.error('加载明细失败: ' + extractErrorMsg(err))
    detail.value = []
  } finally {
    if (!unmounted) loadingDetail.value = false
  }
}

// 切换池: 取消旧订阅 → 拉明细 → 订新订阅
async function switchPool(newId) {
  if (!newId) {
    if (detailCodes.value.length > 0) quoteStore.unsubscribe(detailCodes.value)
    detail.value = []
    return
  }
  if (detailCodes.value.length > 0) {
    quoteStore.unsubscribe(detailCodes.value)
  }
  await loadDetail(newId)
}

async function refresh() {
  await loadPools()
  if (selectedPoolId.value) await loadDetail(selectedPoolId.value)
}

// ============ 行情格式化 (slot inline) ============
// 展示走 #column-${key} inline slot — 支持 A股红涨绿跌 (formatter 只能返字符串, 无法加 class)
// 行 row = mergedData 行, 字段已包含 last_price / change_pct / change_amt / .../ null/undefined

// 按标的 scale 决定小数位 (复用 stocksStore)
function getScale(code) {
  const stock = stocksStore.cache?.find?.(s => s.stock_code === code)
  return stock?.scale ?? 2
}

// 涨跌色 class (红涨绿跌, A股) — null/undefined 返空
function priceColorClass(change) {
  if (change == null) return ''
  if (change > 0) return 'price-up'
  if (change < 0) return 'price-down'
  return ''
}

// 最新价 class — 跟随涨跌额染色
function formatPriceClass(row) {
  return priceColorClass(row.change_amt)
}

// 涨跌幅/涨跌额 class
function formatChangeClass(row) {
  return priceColorClass(row.change_pct)
}

// 最新价
function formatPrice(row) {
  const code = row.stock_code
  const v = row.last_price
  if (v == null) return '--'
  return v.toFixed(getScale(code))
}

// 涨跌幅
function formatChangePct(row) {
  const v = row.change_pct
  if (v == null) return '--'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

// 涨跌额
function formatChangeAmt(row) {
  const code = row.stock_code
  const v = row.change_amt
  if (v == null) return '--'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(getScale(code))}`
}

// 通用字段 (open_price / high_price / low_price / prev_close)
function formatField(row, key) {
  const code = row.stock_code
  const v = row[key]
  if (v == null) return '--'
  return Number(v).toFixed(getScale(code))
}

// 成交量 (手)
function formatVolume(row) {
  const v = row.volume
  if (v == null) return '--'
  return (v / 100).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

// 成交额 (元 → 万元)
function formatAmount(row) {
  const v = row.amount
  if (v == null) return '--'
  return (v / 10000).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

// ============ 错误处理 ============
function extractErrorMsg(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => `${(d.loc || []).join('.')}: ${d.msg || d.type || ''}`).join('; ')
  }
  if (detail && typeof detail === 'object') {
    return detail.msg || detail.code || JSON.stringify(detail)
  }
  return err?.message || '未知错误'
}

// ============ 生命周期 ============
onMounted(async () => {
  await loadPools()
  // watch 触发 loadDetail
})

// 切换池 → 重订
watch(selectedPoolId, (newId, oldId) => {
  if (newId === oldId) return
  switchPool(newId)
})
</script>

<style scoped>
.stkpool-view-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--space-4, 16px);
  gap: var(--space-3, 12px);
  background: var(--bg-base, #f7f8fa);
}

.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3, 12px) var(--space-4, 16px);
  background: var(--bg-elevated, #fff);
  border-radius: var(--radius-md, 6px);
  box-shadow: var(--shadow-card, 0 1px 4px rgba(0, 0, 0, 0.04));
}

.pool-picker {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
}

.pool-picker .label {
  font-weight: 500;
  color: var(--text-secondary, #606266);
  font-size: 14px;
}

.pool-meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2, 8px);
  margin-left: var(--space-2, 8px);
}

.pool-meta .remark {
  font-size: 13px;
  color: var(--text-secondary, #909399);
}

.view-main {
  flex: 1;
  min-height: 0;
  background: var(--bg-elevated, #fff);
  border-radius: var(--radius-md, 6px);
  padding: var(--space-3, 12px);
  box-shadow: var(--shadow-card, 0 1px 4px rgba(0, 0, 0, 0.04));
}

.detail-line {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2, 8px);
}

.detail-code {
  font-weight: 600;
  color: var(--text-primary, #303133);
}

.detail-name {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}

/* A 股配色: 红涨绿跌 */
.price-up {
  color: var(--color-up, #f56c6c);
  font-weight: 600;
}
.price-down {
  color: var(--color-down, #67c23a);
  font-weight: 600;
}
.price-flat {
  color: var(--text-primary, #303133);
}
.cell-na {
  color: var(--text-placeholder, #c0c4cc);
}
</style>