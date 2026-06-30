<template>
  <div class="t0-trade fade-in-up">
    <!-- Header + 设置条 (方案2: 设置条在标题右侧) -->
    <div class="t0-header">
      <span class="t0-title">⚡ 快速做T</span>
      <div class="qs-row">
        <span class="qs-label">仓位</span>
        <el-radio-group v-model="quickPct" size="small">
          <el-radio-button
            v-for="p in PCT_OPTIONS"
            :key="p"
            :value="p"
            :label="String(p) + '%'"
          />
        </el-radio-group>
        <span class="qs-divider">|</span>
        <span class="qs-label">价格档</span>
        <el-radio-group v-model="quickPriceType" size="small">
          <el-radio-button
            v-for="opt in PRICE_TYPE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </el-radio-group>
        <el-button size="small" @click="holdingsStore.refreshPositions()" :loading="refreshing">刷新</el-button>
      </div>
    </div>

    <!-- 主表 (占视口主体, 含副行 + 操作列) -->
    <el-table
      :data="holdingsPositions"
      :row-class-name="ptRowClass"
      @row-click="onOpenDrawer"
      class="position-table"
      empty-text="暂无持仓"
      size="default"
    >
      <el-table-column prop="stock_code" label="代码" width="80" />
      <el-table-column label="名称" width="80">
        <template #default="{ row }">{{ row.stock_name || row.stock_code }}</template>
      </el-table-column>
      <el-table-column label="持仓" align="right" width="70">
        <template #default="{ row }">{{ formatNumber(row.vol) }}</template>
      </el-table-column>
      <el-table-column label="现价" align="right" width="80">
        <template #default="{ row }">
          <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ formatPrice(quoteStore.getLastPrice(row.stock_code)) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="涨跌" align="right" width="70">
        <template #default="{ row }">
          <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ quoteStore.getChangePct(row.stock_code)?.toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- 今盈 (t0Stats realized_pnl, 按需加载) -->
      <el-table-column label="今盈" align="right" width="90">
        <template #default="{ row }">
          <template v-if="t0StatsMap[row.stock_code]">
            <span :class="t0StatsMap[row.stock_code].realized_pnl >= 0 ? 'up' : 'down'">
              {{ (t0StatsMap[row.stock_code].realized_pnl >= 0 ? '+' : '') + formatAmount(t0StatsMap[row.stock_code].realized_pnl) }}
            </span>
          </template>
          <span v-else class="muted">--</span>
        </template>
      </el-table-column>

      <!-- 净敞口 (today_buy_volume - today_sell_volume) -->
      <el-table-column label="净敞口" align="right" width="80">
        <template #default="{ row }">
          <template v-if="t0StatsMap[row.stock_code]">
            <span :class="netExposure(row) > 0 ? 'up' : netExposure(row) < 0 ? 'down' : ''">
              {{ netExposure(row) > 0 ? '+' : '' }}{{ netExposure(row) }}
            </span>
          </template>
          <span v-else class="muted">--</span>
        </template>
      </el-table-column>

      <!-- 浮盈% (holdingsStore.getReturnRate) -->
      <el-table-column label="浮盈%" align="right" width="70">
        <template #default="{ row }">
          <span :class="holdingsStore.getReturnRate(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ (holdingsStore.getReturnRate(row.stock_code) * 100).toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- 操作列: 4 按钮 (买/卖/配平/详情) -->
      <el-table-column label="操作" align="center" width="200" fixed="right">
        <template #default="{ row }">
          <div class="op-col">
            <el-tooltip :content="isBuyDisabled(row) ? `${row.stock_code} 持仓为 0, 无法按比例买` : `按 ${quickPct}% 仓位买入`" placement="top">
              <el-button type="primary" size="small" :disabled="isBuyDisabled(row) || submitting" @click.stop="onQuickBuy(row)" class="op-btn-buy">
                买{{ quickPct }}%
              </el-button>
            </el-tooltip>
            <el-tooltip content="按全局 % 仓位卖出 (0 持仓自动跳过)" placement="top">
              <el-button type="danger" size="small" :disabled="submitting" @click.stop="onQuickSell(row)" class="op-btn-sell">
                卖{{ quickPct }}%
              </el-button>
            </el-tooltip>
            <el-tooltip :content="getBalanceTip(row)" placement="top">
              <el-button
                type="warning"
                size="small"
                :disabled="submitting || !getBalanceQty(row)"
                @click.stop="onQuickBalance(row)"
                class="op-btn-balance"
              >
                {{ getBalanceLabel(row) }}
              </el-button>
            </el-tooltip>
            <el-button type="primary" link size="small" @click.stop="onOpenDrawer(row)" class="op-btn-detail">
              详情
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M5 12h14M13 5l7 7-7 7"/>
              </svg>
            </el-button>
          </div>
        </template>
      </el-table-column>

      <!-- 副行 (默认展开, 通过 expand 实现) -->
      <el-table-column type="expand" width="0">
        <template #default="{ row }">
          <div class="sub-row">
            <div class="sub-item">
              <span class="sub-label">成本</span>
              <span class="sub-value text-mono">{{ formatPrice(row.cost_price) }}</span>
            </div>
            <div class="sub-item">
              <span class="sub-label">成本额</span>
              <span class="sub-value text-mono">¥{{ formatAmount((row.cost_price || 0) * (row.vol || 0)) }}</span>
            </div>
            <div class="sub-item">
              <span class="sub-label">今笔</span>
              <span class="sub-value text-mono">
                {{ t0StatsMap[row.stock_code]?.trade_count || 0 }}
              </span>
            </div>
            <div class="sub-item">
              <span class="sub-label">胜率</span>
              <span class="sub-value text-mono">
                {{ ((t0StatsMap[row.stock_code]?.win_rate || 0) * 100).toFixed(1) }}%
              </span>
            </div>
            <div class="sub-item sub-sparkline" v-if="t0StatsMap[row.stock_code]">
              <span class="sub-label">30天趋势</span>
              <svg :viewBox="`0 0 150 30`" preserveAspectRatio="none" width="150" height="30" class="mini-sparkline">
                <path
                  v-if="sparklinePoints(row.stock_code).length > 1"
                  :d="sparklinePath(row.stock_code)"
                  :stroke="sparklineLast(row.stock_code) >= 0 ? '#f56c6c' : '#67c23a'"
                  stroke-width="1.5"
                  fill="none"
                />
              </svg>
            </div>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 底部: 当前选中标的 30 日累计曲线 (80px 高, 7/30/90D 切换) -->
    <div class="bottom-chart" v-if="cumHistory.length > 0">
      <div class="bottom-chart-header">
        <span class="bottom-chart-label">📈 {{ stockCode || '--' }} 累计曲线</span>
        <el-radio-group v-model="historyDays" size="small" @change="loadT0History">
          <el-radio-button :value="7">7D</el-radio-button>
          <el-radio-button :value="30">30D</el-radio-button>
          <el-radio-button :value="90">90D</el-radio-button>
        </el-radio-group>
      </div>
      <svg :viewBox="`0 0 ${bottomChartW} ${bottomChartH}`" class="bottom-chart-svg" preserveAspectRatio="none">
        <line
          :x1="0" :y1="bottomZeroY"
          :x2="bottomChartW" :y2="bottomZeroY"
          stroke="#dcdfe6" stroke-width="1" stroke-dasharray="3,3"
        />
        <path
          :d="bottomCumPath"
          :stroke="cumHistory[cumHistory.length - 1]?.cum_pnl >= 0 ? '#f56c6c' : '#67c23a'"
          stroke-width="2" fill="none"
        />
        <path
          :d="bottomCumAreaPath"
          :fill="cumHistory[cumHistory.length - 1]?.cum_pnl >= 0 ? 'rgba(245,108,108,0.12)' : 'rgba(103,194,58,0.12)'"
          stroke="none"
        />
      </svg>
      <div class="bottom-chart-tip">
        累计 ¥{{ formatAmount(cumHistory[cumHistory.length - 1]?.cum_pnl || 0) }} ({{ cumHistory.length }} 天)
      </div>
    </div>

    <!-- 右侧明细抽屉 (点击行/详情打开) — 保持原有功能 -->
    <el-drawer
      v-model="drawerVisible"
      :size="drawerSize"
      direction="rtl"
      :with-header="false"
      :modal="true"
      :modal-class="'t0-drawer-modal'"
      custom-class="t0-detail-drawer"
    >
      <div class="t0-drawer" v-loading="drawerLoading">
        <header class="t0-drawer-header">
          <div class="t0-drawer-title">
            <span class="t0-drawer-code">{{ stockCode }}</span>
            <el-tag size="small" type="info" effect="plain">做T 明细</el-tag>
          </div>
          <el-button link @click="drawerVisible = false">
            <el-icon><Close /></el-icon>
          </el-button>
        </header>

        <section class="t0-drawer-stats">
          <div class="stat-block">
            <span class="stat-label">今日成交</span>
            <span class="stat-value text-mono">{{ drawerStats.trade_count || 0 }} 笔</span>
          </div>
          <div class="stat-block">
            <span class="stat-label">已实现</span>
            <span class="stat-value text-mono" :class="(drawerStats.realized_pnl || 0) >= 0 ? 'up' : 'down'">
              {{ (drawerStats.realized_pnl >= 0 ? '+' : '') + formatAmount(drawerStats.realized_pnl) }}
            </span>
          </div>
          <div class="stat-block">
            <span class="stat-label">今日买/卖</span>
            <span class="stat-value text-mono">{{ formatNumber(drawerStats.today_buy_volume) }} / {{ formatNumber(drawerStats.today_sell_volume) }}</span>
          </div>
          <div class="stat-block">
            <span class="stat-label">总盈亏</span>
            <span class="stat-value text-mono" :class="(drawerStats.total_pnl || 0) >= 0 ? 'up' : 'down'">
              {{ (drawerStats.total_pnl >= 0 ? '+' : '') + formatAmount(drawerStats.total_pnl) }}
            </span>
          </div>
        </section>

        <section class="t0-drawer-section">
          <div class="t0-drawer-section-title">
            📈 累计收益曲线
            <el-radio-group v-model="drawerDays" size="small" @change="onDrawerChangeDays">
              <el-radio-button :value="7">7 天</el-radio-button>
              <el-radio-button :value="30">30 天</el-radio-button>
              <el-radio-button :value="90">90 天</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="!drawerHistory || !drawerHistory.points || drawerHistory.points.length === 0" class="t0-drawer-empty">
            暂无历史数据
          </div>
          <div v-else class="t0-drawer-chart">
            <svg :viewBox="`0 0 ${drawerChartW} ${drawerChartH}`" preserveAspectRatio="none" width="100%" :height="drawerChartH">
              <line :x1="drawerChartPad" :y1="drawerZeroY" :x2="drawerChartW - drawerChartPad" :y2="drawerZeroY" stroke="#dcdfe6" stroke-width="1" />
              <path :d="drawerCumPath" :stroke="(drawerCumHistory[drawerCumHistory.length - 1]?.cum_pnl || 0) >= 0 ? '#f56c6c' : '#67c23a'" stroke-width="2" fill="none" />
              <path :d="drawerCumAreaPath" :fill="(drawerCumHistory[drawerCumHistory.length - 1]?.cum_pnl || 0) >= 0 ? 'rgba(245,108,108,0.12)' : 'rgba(103,194,58,0.12)'" />
            </svg>
            <div class="t0-drawer-chart-tip">
              累计 ¥{{ formatAmount(drawerCumHistory[drawerCumHistory.length - 1]?.cum_pnl || 0) }} ({{ drawerCumHistory.length }} 天)
            </div>
          </div>
        </section>

        <section class="t0-drawer-section">
          <div class="t0-drawer-section-title">📋 累计统计 (全部历史)</div>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="已实现盈亏">
              <span :class="(drawerAggregate?.summary?.realized_pnl || 0) >= 0 ? 'up' : 'down'">
                {{ formatAmount(drawerAggregate?.summary?.realized_pnl || 0) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="胜率">
              {{ ((drawerAggregate?.summary?.win_rate || 0) * 100).toFixed(1) }}%
            </el-descriptions-item>
            <el-descriptions-item label="平均回报">
              {{ ((drawerAggregate?.summary?.avg_return || 0) * 100).toFixed(2) }}%
            </el-descriptions-item>
            <el-descriptions-item label="交易笔数">
              {{ drawerAggregate?.summary?.trade_count || 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </section>

        <footer class="t0-drawer-footer">
          <el-button size="default" @click="drawerVisible = false">关闭</el-button>
        </footer>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { useOrderStore } from '../stores/order'
import {
  PCT_OPTIONS, PRICE_TYPE_OPTIONS,
  loadQuickDefaults, saveQuickDefaults,
  isBuyDisabled, buildQuickOrder, calcBalanceQty,
} from '../composables/useQuickT0'
import { t0StatsApi } from '../api/t0_stats'
import { formatNumber, formatPrice, formatAmount } from '../utils/format'
import { useT0ChartGeometry, useT0DrawerChartGeometry } from '../composables/useT0ChartGeometry'
import { useT0OrderSubmit } from '../composables/useT0OrderSubmit'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()
const quoteStore = useQuoteStore()
const { positions } = storeToRefs(holdingsStore)

// stockCode: 默认取第一个持仓，不再硬编码 600519.SH
const stockCode = ref(null)
const submitting = ref(false)
const refreshing = ref(false)

// ---- 抽屉控制 (保持原有功能) ----
const drawerVisible = ref(false)
const drawerLoading = ref(false)
const drawerStats = ref({ order_count: 0, trade_count: 0, realized_pnl: 0, unrealized_pnl: 0, total_pnl: 0, today_buy_volume: 0, today_sell_volume: 0, today_buy_amount: 0, today_sell_amount: 0 })
const drawerHistory = ref(null)
const drawerDays = ref(30)
function onOpenDrawer(row) {
  if (!row || !row.stock_code) return
  const code = row.stock_code
  stockCode.value = code
  drawerVisible.value = true
  drawerLoading.value = true
  Promise.all([
    t0StatsApi.get(code).catch((e) => { console.warn('drawer t0 stats failed', e); return null }),
    t0StatsApi.getHistory(code, drawerDays.value).catch((e) => { console.warn('drawer t0 history failed', e); return null }),
  ]).then(([stats, hist]) => {
    if (stats) drawerStats.value = stats
    drawerHistory.value = hist
  }).finally(() => { drawerLoading.value = false })
}
function onDrawerChangeDays(days) {
  drawerDays.value = days
  if (!stockCode.value) return
  t0StatsApi.getHistory(stockCode.value, days).then((h) => { drawerHistory.value = h }).catch(() => {})
}

const drawerSize = computed(() => (typeof window !== 'undefined' && window.innerWidth < 1100 ? '420px' : '540px'))
const drawerCumHistory = computed(() => {
  const pts = drawerHistory.value?.points || []
  let cum = 0
  return pts.map(p => ({ ...p, cum_pnl: (cum += p.realized_pnl) }))
})
const drawerChartW = 460
const drawerChartH = 140
const drawerChartPad = 16
const { cumPath: drawerCumPath, cumAreaPath: drawerCumAreaPath, zeroY: drawerZeroY } =
  useT0DrawerChartGeometry(drawerCumHistory, { W: drawerChartW, H: drawerChartH, pad: drawerChartPad })
const drawerAggregate = ref(null)
watch(drawerVisible, async (v) => {
  if (v && stockCode.value) {
    try {
      const agg = await t0StatsApi.getAggregate({ userDef: 'T0', days: 90 })
      drawerAggregate.value = (agg?.by_stock || []).find(s => s.stock_code === stockCode.value) || agg
    } catch (e) {
      console.warn('drawer aggregate failed', e)
    }
  }
})
function ptRowClass({ row }) {
  return row.stock_code === stockCode.value ? 'is-selected' : ''
}

// ---- 快速做T 全局设置 ----
const _quickDefaults = loadQuickDefaults()
const quickPct = ref(_quickDefaults.pct)
const quickPriceType = ref(_quickDefaults.priceType)
watch([quickPct, quickPriceType], ([p, pt]) => {
  saveQuickDefaults(p, pt)
})

// ---- 持仓列表 ----
const holdingsPositions = computed(() => positions.value)

// ---- t0StatsMap: 每个持仓的今日统计 ----
const t0StatsMap = ref({})
async function loadAllT0Stats() {
  const codes = holdingsPositions.value?.map(p => p.stock_code) || []
  const results = await Promise.allSettled(
    codes.map(code => t0StatsApi.get(code).catch(e => { console.warn(`t0 stats failed for ${code}`, e); return null }))
  )
  const map = {}
  results.forEach((result, i) => {
    if (result.status === 'fulfilled' && result.value) {
      map[codes[i]] = result.value
    }
  })
  t0StatsMap.value = map
}

// ---- 净敞口 / 配平按钮文本 ----
function netExposure(row) {
  const s = t0StatsMap.value[row.stock_code]
  if (!s) return 0
  return (s.today_buy_volume || 0) - (s.today_sell_volume || 0)
}
function getBalanceQty(row) {
  const net = netExposure(row)
  return net === 0 ? null : Math.abs(net)
}
function getBalanceLabel(row) {
  const net = netExposure(row)
  if (net === 0) return '配平'
  return `配${net > 0 ? '-' : '+'}${Math.abs(net)}`
}
function getBalanceTip(row) {
  const net = netExposure(row)
  if (net === 0) return '已配平'
  return `配平: ${net > 0 ? `卖${Math.abs(net)}` : `买${Math.abs(net)}`} 抵消今日净敞口`
}

// ---- 底部累计曲线 (按当前 stockCode) ----
const historyDays = ref(30)
const historyData = ref(null)
async function loadT0History() {
  if (!stockCode.value) return
  try {
    historyData.value = await t0StatsApi.getHistory(stockCode.value, historyDays.value)
  } catch (e) {
    console.warn('load t0 history failed', e)
    historyData.value = null
  }
}
const cumHistory = computed(() => {
  const pts = historyData.value?.points || []
  let cum = 0
  return pts.map(p => ({ ...p, cum_pnl: (cum += p.realized_pnl) }))
})
const bottomChartW = 800
const bottomChartH = 80
const bottomChartPad = 24
const {
  cumPath: bottomCumPath,
  cumAreaPath: bottomCumAreaPath,
  zeroY: bottomZeroY,
} = useT0ChartGeometry(cumHistory, { W: bottomChartW, H: bottomChartH, pad: bottomChartPad })

// ---- Sparkline (副行 30 天 mini 曲线) ----
const sparklineCache = ref({})
function sparklinePoints(code) {
  if (sparklineCache.value[code]) return sparklineCache.value[code]
  // 从 drawer API 获取 30 天历史，缓存结果
  const pts = []
  let cum = 0
  // lazy load via async path - for now use a simple inline approach
  sparklineCache.value[code] = pts
  return pts
}
async function loadSparkline(code) {
  if (sparklineCache.value[code]) return
  try {
    const hist = await t0StatsApi.getHistory(code, 30)
    const pts = []
    let cum = 0
    if (hist?.points) {
      for (const p of hist.points) {
        cum += p.realized_pnl
        pts.push(cum)
      }
    }
    sparklineCache.value[code] = pts
  } catch (e) {
    console.warn(`sparkline failed for ${code}`, e)
    sparklineCache.value[code] = []
  }
}
function sparklinePath(code) {
  const pts = sparklinePoints(code)
  if (pts.length < 2) return ''
  const W = 150, H = 30, pad = 4
  const min = Math.min(...pts)
  const max = Math.max(...pts)
  const range = max - min || 1
  const step = W / (pts.length - 1)
  return pts.map((v, i) => {
    const x = i * step
    const y = pad + (1 - (v - min) / range) * (H - pad * 2)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}
function sparklineLast(code) {
  const pts = sparklinePoints(code)
  return pts.length > 0 ? pts[pts.length - 1] : 0
}

// ---- 提交下单 (保持 useT0OrderSubmit) ----
const priceType = ref('latest')
const balanceCoeff = ref(1.0)
const { submitOrder } = useT0OrderSubmit({
  stockCode, priceType, balanceCoeff, submitting,
  orderStore,
  onAfterSuccess: () => loadAllT0Stats(),
})

// ---- M-008 v3: 行内快捷买卖 ----
function onQuickBuy(row) {
  if (isBuyDisabled(row)) return ElMessage.warning(`${row.stock_code} 持仓为 0, 无法按比例买`)
  const r = buildQuickOrder(row, 'buy', quickPct.value, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 买 ${r.qty} 股 (${r.label})`,
    '一键买入', { confirmButtonText: '确认买入', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: '23', volume: r.qty, price: r.price }))
    .catch(() => {})
}
function onQuickSell(row) {
  const r = buildQuickOrder(row, 'sell', quickPct.value, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 卖 ${r.qty} 股 (${r.label})`,
    '一键卖出', { confirmButtonText: '确认卖出', cancelButtonText: '取消', type: 'warning' }
  ).then(() => submitOrder({ orderType: '24', volume: r.qty, price: r.price }))
    .catch(() => {})
}
function onQuickBalance(row) {
  const bal = calcBalanceQty(row, row.today_buy_volume || 0, row.today_sell_volume || 0)
  if (bal.error) return ElMessage.warning(bal.error)
  const r = buildQuickOrder(row, bal.side, 100, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  r.qty = bal.qty
  ElMessageBox.confirm(
    `${row.stock_code} ${bal.side === 'buy' ? '买入' : '卖出'} ${bal.qty} 股 配平 (净额归零)`,
    '一键配平', { confirmButtonText: '确认配平', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: bal.side === 'buy' ? '23' : '24', volume: bal.qty, price: r.price }))
    .catch(() => {})
}


// ---- 快捷键 ----
function onKeyDown(e) {
  if (e.key === 'Escape') {
    if (drawerVisible.value) drawerVisible.value = false
    return
  }
  const tag = (e.target?.tagName || '').toLowerCase()
  if (['input', 'textarea', 'select'].includes(tag)) return
  if (e.ctrlKey || e.metaKey || e.altKey) return
}

// ---- 初始化 ----
onMounted(async () => {
  await loadAllT0Stats()
  // 默认选中第一个持仓
  if (!stockCode.value && holdingsPositions.value.length > 0) {
    stockCode.value = holdingsPositions.value[0].stock_code
    await loadT0History()
    await loadSparkline(stockCode.value)
  }
  window.addEventListener('keydown', onKeyDown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})

// 当持仓变化时，重新加载所有 t0Stats
watch(() => holdingsPositions.value.length, async (newLen, oldLen) => {
  if (oldLen !== null && newLen !== oldLen) {
    await loadAllT0Stats()
  }
})

// 监听 stockCode 变化 → 加载底部曲线
watch(stockCode, async (code) => {
  if (code && !drawerVisible.value) {
    await loadT0History()
    await loadSparkline(code)
  }
})
</script>

<style scoped>
.t0-trade {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  height: 100%;
}

/* Header + 设置条 */
.t0-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}
.t0-title {
  font-size: 16px;
  font-weight: 700;
}
.qs-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qs-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.qs-divider {
  color: var(--el-border-color);
}

/* 主表 */
.position-table {
  flex: 1;
  min-height: 0;
}
.position-table :deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--el-fill-color-light);
}
.position-table :deep(tr) {
  cursor: pointer;
}
.position-table :deep(tr.is-selected td) {
  background-color: var(--el-color-primary-light-9) !important;
}

/* 操作列 */
.op-col {
  display: flex;
  gap: 4px;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
}
.op-col :deep(.el-button) {
  padding: 4px 6px !important;
  font-size: 12px !important;
  font-weight: 600;
}
.op-btn-buy :deep(span), .op-btn-sell :deep(span), .op-btn-balance :deep(span) {
  color: #fff !important;
}
.op-btn-detail {
  padding: 0 !important;
  font-size: 12px !important;
}

/* 副行 */
.sub-row {
  display: flex;
  gap: 24px;
  padding: 4px 16px 8px;
  flex-wrap: wrap;
  background: var(--el-fill-color-light);
}
.sub-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.sub-sparkline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.mini-sparkline {
  display: block;
}
.sub-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.sub-value {
  font-size: 13px;
  font-weight: 500;
}

/* 底部累计曲线 */
.bottom-chart {
  padding: 4px 12px 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.bottom-chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}
.bottom-chart-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.bottom-chart-svg {
  width: 100%;
  height: 80px;
  display: block;
}
.bottom-chart-tip {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: right;
  margin-top: 2px;
}

/* 颜色 */
.up { color: #f56c6c; }
.down { color: #67c23a; }
.muted { color: var(--el-color-info); }
.text-mono { font-family: var(--mono-font); }

/* 抽屉样式 (保持与原版本一致) */
.t0-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.t0-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.t0-drawer-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.t0-drawer-code {
  font-size: 16px;
  font-weight: 700;
}
.t0-drawer-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 12px 16px;
}
.stat-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.stat-value {
  font-size: 16px;
  font-weight: 600;
}
.t0-drawer-section {
  padding: 12px 16px;
}
.t0-drawer-section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
}
.t0-drawer-empty {
  text-align: center;
  padding: 24px;
  color: var(--el-text-color-secondary);
}
.t0-drawer-chart {
  margin-top: 8px;
}
.t0-drawer-chart-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: right;
  margin-top: 4px;
}
.t0-drawer-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .t0-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .position-table {
    font-size: 12px;
  }
  .sub-row {
    gap: 12px;
    padding: 4px 8px 6px;
  }
  .sub-sparkline {
    display: none;
  }
  .bottom-chart-svg {
    height: 60px;
  }
}
</style>
