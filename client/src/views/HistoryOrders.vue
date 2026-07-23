<!--
  HistoryOrders.vue — 历史委托视图（v12 + v13 预设 chip + 强制历史范围）

  数据源：api.getOrders({ startDate, endDate, stockCode }) 局部查询
  不走 Pinia（历史数据非"实时"语义）
  不入 IDB（页面切换后下次进来重新拉）

  v13 修订:
    - 加 4 个预设 chip (昨日 / 最近三天 / 最近一周 / 最近一个月), 点击即查 (不含今日)
    - picker 禁 today 及未来日期 (历史语义约束)
    - onMounted 留空 (无默认查询, 用户主动选 chip 或 picker)
    - chip ↔ picker 双向联动 (chip 自动高亮响应 picker 范围匹配)
-->
<template>
  <div class="history-orders-view fade-in-up">
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
        <div class="pill-label">委托笔数</div>
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
        :default-sort="{ prop: 'order_time', order: 'descending' }"
      >
        <!-- v71: 15 列走 COL 常量 -->
        <el-table-column prop="trd_date" label="交易日" sortable v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_time" label="时间" sortable v-bind="COL.TIME">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="委托编号" show-overflow-tooltip v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="股票代码" v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_name" label="名称" show-overflow-tooltip v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-secondary">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_type" label="方向" v-bind="COL.makeDict('direction', { width: 100, align: 'center', headerAlign: 'center' })">
          <template #default="{ row }">
            <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="委托量" v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="委托价" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_volume" label="成交量" v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_price" label="成交均价" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatPrice(row.avg_price, row.stock_code) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成交金额" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatAmount(row.traded_amount) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cancelled_volume" label="撤单量" v-bind="COL.makeDict('number', { width: 85, align: 'right', headerAlign: 'right' })">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.cancelled_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" v-bind="COL.STATUS">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
        </el-table-column>
        <el-table-column prop="order_id" label="合同序号" show-overflow-tooltip v-bind="COL.makeDict('id', { minWidth: 100 })">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_id }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="hasQueried ? '该区间内无委托记录' : '请选择起止日期查询'"
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
import { formatMoney, formatAmount, formatNumber, STATUS_LABEL } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'
import { shiftDateStr } from '../utils/date'

/**
 * 历史委托视图（v12 + v13 trade-page-redesign-v2）
 *
 * 数据契约（spec/orders-trades-history-query.md）：
 * - 数据源：api.getOrders({ startDate, endDate, stockCode }) 局部 HTTP 查询
 * - 不走 Pinia holdings（历史数据非"实时"语义）
 * - 不入 IDB（页面切换后下次进来重新拉）
 * - 前端校验 startDate <= endDate（按钮 disabled + alert）
 * - 排序：服务端 ORDER BY order_time DESC
 *
 * v13 修订:
 * - onMounted 留空 (无默认查询, 用户主动选 chip 或 picker)
 * - 4 个预设 chip (昨日/最近三天/最近一周/最近一个月), 点击即查
 * - chip 范围严格不含 today (历史语义约束)
 * - picker 禁用 today+ (历史语义 UI 保险丝)
 * - chip ↔ picker 双向联动高亮 (computed activePreset)
 */

// 4 个预设 chip (日历日, 严格不含 today)
const PRESETS = [
  { label: '昨日',     startOffset: -1,  endOffset: -1,  tooltip: '查询昨天 1 天（不含今日）' },
  { label: '最近三天', startOffset: -3,  endOffset: -1,  tooltip: '查询 today-3 ~ today-1, 不含今日' },
  { label: '最近一周', startOffset: -7,  endOffset: -1,  tooltip: '查询 today-7 ~ today-1, 不含今日' },
  { label: '最近一个月', startOffset: -30, endOffset: -1, tooltip: '查询 today-30 ~ today-1, 不含今日' }
]

// 今日 YYYYMMDD (本地时区)
function todayYYYYMMDD() {
  const dt = new Date()
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const d = String(dt.getDate()).padStart(2, '0')
  return `${y}${m}${d}`
}

// picker 禁 today+: 任意 >= today 的日期不能选
function isAfterToday(date) {
  // el-date-picker 给的是 Date 对象
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}${m}${d}` >= todayYYYYMMDD()
}

// 计算预设范围 [startYYYYMMDD, endYYYYMMDD]
function presetRange(preset) {
  const today = todayYYYYMMDD()
  return [shiftDateStr(today, preset.startOffset), shiftDateStr(today, preset.endOffset)]
}

// 查询条件
const dateRange = ref(null)
const stockCode = ref('')

// 查询结果（局部 state, 不入 Pinia / IDB）
const results = ref([])
const loading = ref(false)
const hasQueried = ref(false)

// 分页
const page = ref(1)
const pageSize = ref(20)

// 校验：startDate <= endDate
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

// chip ↔ picker 双向联动高亮: 当前 dateRange == preset range 时, 该 chip 高亮
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
    const opts = { startDate, endDate }
    if (stockCode.value) opts.stockCode = stockCode.value
    const data = await api.getOrders(opts)
    results.value = Array.isArray(data) ? data : []
    hasQueried.value = true
    page.value = 1  // 重新分页
  } catch (e) {
    // 错误已由 axios 拦截器统一弹 ElMessage.error
    results.value = []
  } finally {
    loading.value = false
  }
}

// 点 chip: 立刻设范围 + 立即查询 (不需要再点"查询"按钮)
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

function exportCSV() {
  const header = ['交易日', '时间', '委托编号', '类型', '股票代码', '方向',
                  '委托量', '委托价', '成交量', '成交金额', '状态', '合同序号']
  const rows = results.value.map((o) => [
    o.trd_date,
    o.order_time,
    o.order_no,
    Number(o.order_flag) === 1 ? '撤单' : '委托',
    o.stock_code,
    o.order_type === '23' ? '买入' : (o.order_type === '24' ? '卖出' : o.order_type),
    o.volume,
    o.price,
    o.traded_volume,
    o.traded_amount,
    STATUS_LABEL[o.status] || o.status,
    o.order_id || ''
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `历史委托_${queryLabel.value}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

// v13 trade-page-redesign-v2: onMounted 留空 (无默认查询, 用户主动选 chip 或 picker)
//   旧 v12 行为 [activeDay, activeDay] 已被 Trade.vue 内嵌 mini-panel 承担
//   history view 严格只服务历史数据 (dateRange MUST ≤ today-1)
</script>

<style scoped>
.history-orders-view {
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
  .stats-row { grid-template-columns: 1fr; }
}
</style>