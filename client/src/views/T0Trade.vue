<template>
  <div class="t0-trade fade-in-up">
    <!-- Header + 设置条: 标题 + 仓位% + 价格档 + 刷新 + task 入口 -->
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
        <span class="qs-divider">|</span>
        <!-- v54: task 快速选择器（精简无 quota 框架, 移到这里） -->
        <el-tooltip content="选择/取消当前做T归属的 task；新建请用管理任务入口" placement="top">
          <el-select
            v-model="selectedTaskId"
            placeholder="归属 task (可选)"
            clearable
            size="small"
            filterable
            class="t0-task-quick-select"
            @clear="selectedTaskId = null"
            no-data-text="暂无活跃 task，请新建"
          >
            <el-option
              v-for="t in filteredActiveTasks"
              :key="t.id"
              :value="t.id"
              :label="`#${t.id} ${t.stock_code}`"
            />
          </el-select>
        </el-tooltip>
        <el-button size="small" link type="primary" @click="onManageTasks">管理任务</el-button>
        <el-button size="small" @click="holdingsStore.refreshPositions()" :loading="refreshing">刷新</el-button>
      </div>
    </div>

    <!-- 主表: 11 列精简布局 (v54 quick-t0-revamp) -->
    <el-table
      :data="sortedRows"
      :row-class-name="ptRowClass"
      @sort-change="onSortChange"
      class="position-table"
      empty-text="暂无持仓"
      size="default"
    >
      <!-- 1. 代码 (100) -->
      <el-table-column prop="stock_code" label="代码" width="100" />

      <!-- 2. 名称 (100) -->
      <el-table-column label="名称" width="100">
        <template #default="{ row }">{{ stockName(row.stock_code) || row.stock_code }}</template>
      </el-table-column>

      <!-- 3. 持仓 (100, sortable) -->
      <el-table-column prop="vol" label="持仓" align="right" width="100" sortable="custom">
        <template #default="{ row }">{{ formatNumber(row.vol) }}</template>
      </el-table-column>

      <!-- 4. 最新价(涨跌幅%) (130, sortable, 单列合并 v54 Q7) -->
      <el-table-column prop="last_price" label="最新价(涨跌幅%)" align="right" width="130" sortable="custom">
        <template #default="{ row }">
          <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ formatPriceAuto(quoteStore.getLastPrice(row.stock_code)) }}
            ({{ quoteStore.getChangePct(row.stock_code) >= 0 ? '+' : '' }}{{ quoteStore.getChangePct(row.stock_code)?.toFixed(2) }}%)
          </span>
        </template>
      </el-table-column>

      <!-- 5. 期初配额 (100) — last_vol (原有持仓, 不递减) -->
      <el-table-column prop="last_vol" label="期初" align="right" width="100">
        <template #default="{ row }">
          <span class="text-mono" :class="formatNumber(row.last_vol) >= 1000 ? '' : 'muted'">
            {{ formatNumber(row.last_vol || 0) }}
          </span>
        </template>
      </el-table-column>

      <!-- 6. 可买 (100, sortable) — calcInitialQuota.maxBuyable 基于 last_vol - 已成交买 -->
      <el-table-column prop="max_buyable" label="可买" align="right" width="100" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono quota-cell" :class="`quota-${quotaLevel(rowInitialQuota(row).maxBuyable)}`">
            {{ formatNumber(rowInitialQuota(row).maxBuyable) }}
          </span>
        </template>
      </el-table-column>

      <!-- 7. 可卖 (100, sortable) — calcInitialQuota.maxSellable 基于 last_vol - 已成交卖 -->
      <el-table-column prop="max_sellable" label="可卖" align="right" width="100" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono quota-cell" :class="`quota-${quotaLevel(rowInitialQuota(row).maxSellable)}`">
            {{ formatNumber(rowInitialQuota(row).maxSellable) }}
          </span>
        </template>
      </el-table-column>

      <!-- 8. 做T盈亏 (100, sortable) — calcT0Pnl = sell_amount - buy_amount -->
      <el-table-column prop="t0_pnl" label="做T盈亏" align="right" width="100" sortable="custom">
        <template #default="{ row }">
          <template v-if="t0StatsMap[row.stock_code]">
            <span :class="t0PnlForRow(row) >= 0 ? 'up' : 'down'">
              {{ (t0PnlForRow(row) >= 0 ? '+' : '') + formatAmount(t0PnlForRow(row)) }}
            </span>
          </template>
          <span v-else class="muted">--</span>
        </template>
      </el-table-column>

      <!-- 9. 做T收益率% (110, sortable) — calcT0ReturnRate = pnl / (last_vol * cost_price) -->
      <el-table-column prop="t0_return_rate" label="做T收益率%" align="right" width="110" sortable="custom">
        <template #default="{ row }">
          <span :class="t0ReturnRateForRow(row) >= 0 ? 'up' : 'down'">
            {{ (t0ReturnRateForRow(row) * 100).toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- 10. 浮盈% (100, sortable, 保留旧 v53) -->
      <el-table-column prop="return_rate" label="浮盈%" align="right" width="100" sortable="custom">
        <template #default="{ row }">
          <span :class="holdingsStore.getReturnRate(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ (holdingsStore.getReturnRate(row.stock_code) * 100).toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- 11. 操作 (180 fixed right) — 4 按钮 (买/卖/配平/详情) -->
      <el-table-column label="操作" align="center" width="180" fixed="right">
        <template #default="{ row }">
          <div class="op-col">
            <el-tooltip :content="buyState(row).tip" placement="top">
              <el-button type="primary" size="small" :disabled="buyState(row).disabled" @click.stop="onQuickBuy(row)" class="op-btn-buy">
                买{{ quickPct }}%
              </el-button>
            </el-tooltip>
            <el-tooltip :content="sellState(row).tip" placement="top">
              <el-button type="danger" size="small" :disabled="sellState(row).disabled" @click.stop="onQuickSell(row)" class="op-btn-sell">
                卖{{ quickPct }}%
              </el-button>
            </el-tooltip>
            <el-tooltip :content="balanceState(row).tip" placement="top">
              <el-button
                type="warning"
                size="small"
                :disabled="balanceState(row).disabled"
                @click.stop="onQuickBalance(row)"
                class="op-btn-balance"
              >
                {{ getBalanceLabel(row) }}
              </el-button>
            </el-tooltip>
            <el-tooltip content="查看做T历史明细" placement="top">
              <el-button type="primary" link size="small" @click.stop="onOpenDrawer(row)" class="op-btn-detail">
                详情
              </el-button>
            </el-tooltip>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- v54: T0Task 管理抽屉 (保留) -->
    <el-drawer v-model="tasksDrawerVisible" title="T0 任务管理" size="70%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskList
        :visible="tasksDrawerVisible"
        embedding="drawer"
        @detail="onOpenTaskDetail"
        @balance="onBalanceTask"
        @close="onCloseTask"
        @create="createDialogVisible = true"
      />
    </el-drawer>

    <el-drawer v-model="tasksDetailVisible" :title="`task #${viewingTaskId} 详情`" size="55%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskDetail v-if="tasksDetailVisible" :task-id="viewingTaskId" embedding="drawer" />
    </el-drawer>

    <T0TaskCreateDialog
      v-model="createDialogVisible"
      :loading="createDialogLoading"
      :default-stock-code="stockCode"
      @submit="onCreateTaskSubmit"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { useOrderStore } from '../stores/order'
import { useAssetStore } from '../stores/asset'
import {
  PCT_OPTIONS, PRICE_TYPE_OPTIONS,
  loadQuickDefaults, saveQuickDefaults,
  isBuyDisabled, buildQuickOrder,
} from '../composables/useQuickT0'
import {
  buyBtnState, sellBtnState, balanceBtnState,
} from '../composables/useT0TradeButtons'
import { useT0Stats } from '../composables/useT0Stats'
import { useT0Keybindings } from '../composables/useT0Keybindings'
// v54: 直接 import quotaLevel (用于可买/可卖颜色), 不依赖 useT0Quota() 整体 hook
import { quotaLevel } from '../composables/useT0Quota'
// v54: 新增 5 纯函数 — 做T盈亏/敞口/期初配额/收益率/配平对手盘价
import {
  calcT0Pnl,
  calcInitialQuota,
  calcT0ReturnRate,
  resolveBalancePrice,
} from '../lib/t0-calc'
import { useUiStore } from '../stores/ui'
import { t0StatsApi } from '../api/t0_stats'
import { useT0TasksStore } from '../stores/t0_tasks'
import T0TaskList from '../components/trade/T0TaskList.vue'
import T0TaskDetail from '../components/trade/T0TaskDetail.vue'
import T0TaskCreateDialog from '../components/trade/T0TaskCreateDialog.vue'
import { t0TasksApi } from '../api/t0_tasks'
import { formatNumber, formatAmount, formatPriceAuto } from '../utils/format'
import { stockName } from '../utils/stockNames'
import { useT0OrderSubmit } from '../composables/useT0OrderSubmit'
import { makeLogger } from '../utils/logger'

const log = makeLogger('T0Trade')

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()
const quoteStore = useQuoteStore()
const assetStore = useAssetStore()
const uiStore = useUiStore()
const t0TasksStore = useT0TasksStore()
const { positions } = storeToRefs(holdingsStore)
const { asset: assetData } = storeToRefs(assetStore)

const stockCode = ref(null)
const submitting = ref(false)
const refreshing = ref(false)

// task 管理
const selectedTaskId = ref(null)
const tasksDrawerVisible = ref(false)
const tasksDetailVisible = ref(false)
const viewingTaskId = ref(null)
const createDialogVisible = ref(false)
const createDialogLoading = ref(false)

const filteredActiveTasks = computed(() => {
  const all = t0TasksStore.activeTasks || []
  if (!stockCode.value) return all
  return all.filter((t) => t.stock_code === stockCode.value)
})
watch([stockCode, filteredActiveTasks], ([code, list]) => {
  if (selectedTaskId.value && !list.find((t) => t.id === selectedTaskId.value)) {
    selectedTaskId.value = null
  }
})

async function onManageTasks() {
  tasksDrawerVisible.value = true
  await t0TasksStore.loadTasks()
}
function onOpenTaskDetail(taskId) {
  viewingTaskId.value = taskId
  tasksDetailVisible.value = true
}
async function onBalanceTask(taskId) {
  try {
    const r = await t0TasksStore.balanceTask(taskId)
    const dir = r.action === 'BUY' ? '买入' : r.action === 'SELL' ? '卖出' : '无需操作'
    ElMessage.info(`task #${taskId} 配平建议：${dir} ${r.volume} 股 — ${r.reason}`)
  } catch (e) {}
}
async function onCloseTask(taskId) {
  if (!confirm(`确认一键平仓 task #${taskId} 到 base_volume？将生成平仓委托`)) return
  try {
    const r = await t0TasksStore.closeTask(taskId)
    ElMessage.success(`task #${taskId} 已平仓：${r.action} ${r.volume} 股`)
    await t0TasksStore.loadTasks()
  } catch (e) {}
}
async function onCreateTaskSubmit(form) {
  createDialogLoading.value = true
  try {
    const t = await t0TasksStore.createTask(form)
    if (t && t.id) {
      ElMessage.success(`task #${t.id} 创建成功，自动选中`)
      if (t.stock_code === stockCode.value) {
        selectedTaskId.value = t.id
      }
    }
    createDialogVisible.value = false
  } finally {
    createDialogLoading.value = false
  }
}

// ---- 做T明细抽屉 (保留基础功能, 不动) ----
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
    t0StatsApi.get(code).catch((e) => { log.warn('drawer t0 stats failed', e); return null }),
    t0StatsApi.getHistory(code, drawerDays.value).catch((e) => { log.warn('drawer t0 history failed', e); return null }),
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

function ptRowClass({ row }) {
  const classes = []
  if (row.stock_code === stockCode.value) classes.push('is-selected')
  if (row.stock_code === selectedRowCode.value) classes.push('is-focused')
  return classes.join(' ')
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

// ---- 排序 + 选中行 (保留 v53) ----
const sortBy = ref(null)
const sortOrder = ref(null)
const selectedRowCode = ref(null)
function onSortChange({ prop, order }) {
  sortBy.value = order ? prop : null
  sortOrder.value = order || null
}
function _rowSortValue(row, key) {
  if (!key) return 0
  switch (key) {
    case 'vol': return Number(row.vol) || 0
    case 'last_price': return quoteStore.getLastPrice(row.stock_code) || 0
    case 'max_buyable': return rowInitialQuota(row).maxBuyable
    case 'max_sellable': return rowInitialQuota(row).maxSellable
    case 't0_pnl': return t0PnlForRow(row)
    case 't0_return_rate': return t0ReturnRateForRow(row)
    case 'return_rate': return holdingsStore.getReturnRate(row.stock_code) || 0
    default: return 0
  }
}
const sortedRows = computed(() => {
  const list = [...holdingsPositions.value]
  if (!sortBy.value || !sortOrder.value) return list
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  list.sort((a, b) => {
    const va = _rowSortValue(a, sortBy.value)
    const vb = _rowSortValue(b, sortBy.value)
    return (va - vb) * dir
  })
  return list
})
function _moveSelection(delta) {
  const list = sortedRows.value
  if (list.length === 0) return
  const curIdx = list.findIndex(r => r.stock_code === selectedRowCode.value)
  let next = curIdx + delta
  if (next < 0) next = 0
  if (next >= list.length) next = list.length - 1
  selectedRowCode.value = list[next].stock_code
}
function _selectedRow() {
  return sortedRows.value.find(r => r.stock_code === selectedRowCode.value)
}

// ---- t0StatsMap: 每个持仓的今日统计 ----
const t0StatsMap = ref({})
async function loadAllT0Stats() {
  const codes = holdingsPositions.value?.map(p => p.stock_code) || []
  const map = await useT0Stats.loadAll(codes)
  t0StatsMap.value = map
}
async function loadDiffT0Stats(newCodes, oldCodes) {
  const oldSet = new Set(oldCodes || [])
  const added = newCodes.filter(c => !oldSet.has(c))
  if (added.length === 0) return
  const addedMap = await useT0Stats.loadAll(added)
  t0StatsMap.value = { ...t0StatsMap.value, ...addedMap }
}

// ---- v54: 纯函数 row 包装 ----
function rowInitialQuota(row) {
  const stats = t0StatsMap.value[row.stock_code]
  return calcInitialQuota(
    { last_vol: row.last_vol ?? row.vol ?? 0 },
    { today_buy_volume: stats?.today_buy_volume ?? 0, today_sell_volume: stats?.today_sell_volume ?? 0 }
  )
}
function t0PnlForRow(row) {
  return calcT0Pnl(t0StatsMap.value[row.stock_code])
}
function t0ReturnRateForRow(row) {
  return calcT0ReturnRate(
    { last_vol: row.last_vol ?? row.vol ?? 0, cost_price: row.cost_price ?? 0 },
    { today_buy_amount: t0StatsMap.value[row.stock_code]?.today_buy_amount ?? 0, today_sell_amount: t0StatsMap.value[row.stock_code]?.today_sell_amount ?? 0 }
  )
}

// ---- v54: 净敞口仍需用（配平按钮文本与 quick 配平）, 但 columns 隐藏 ----
function netExposure(row) {
  const s = t0StatsMap.value[row.stock_code]
  if (!s) return 0
  return (s.today_buy_volume || 0) - (s.today_sell_volume || 0)
}

// ---- v54: 配平按钮 — 价格改用 resolveBalancePrice (买→ask1 / 卖→bid1, Q3) ----
function getBalanceQty(row) {
  const net = netExposure(row)
  return net === 0 ? null : Math.abs(net)
}
function getBalanceLabel(row) {
  const net = netExposure(row)
  if (net === 0) return '配平'
  return `配${net > 0 ? '-' : '+'}${Math.abs(net)}`
}
function _rowBalance(row) {
  const net = netExposure(row)
  if (net === 0) return null
  return { side: net > 0 ? 'sell' : 'buy', qty: Math.abs(net) }
}

// ---- 按钮状态 ----
function buyState(row) {
  return buyBtnState(row, {
    pct: quickPct.value,
    cash: assetData.value?.cash,
    price: quoteStore.getLastPrice(row.stock_code),
    submitting: submitting.value,
  })
}
function sellState(row) {
  return sellBtnState(row, { pct: quickPct.value, submitting: submitting.value })
}
function balanceState(row) {
  return balanceBtnState(row, {
    balance: _rowBalance(row),
    cash: assetData.value?.cash,
    price: quoteStore.getLastPrice(row.stock_code),
    submitting: submitting.value,
  })
}

// ---- 下单 ----
const priceType = ref('latest')
const balanceCoeff = ref(1.0)
const { submitOrder } = useT0OrderSubmit({
  stockCode, priceType, balanceCoeff, submitting,
  orderStore,
  onAfterSuccess: () => loadAllT0Stats(),
})

function onQuickBuy(row) {
  if (isBuyDisabled(row)) return ElMessage.warning(`${row.stock_code} 持仓为 0, 无法按比例买`)
  const r = buildQuickOrder(row, 'buy', quickPct.value, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 买 ${r.qty} 股 (${r.label})`,
    '一键买入', { confirmButtonText: '确认买入', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: '23', volume: r.qty, price: r.price, taskId: selectedTaskId.value }))
    .catch(() => {})
}
function onQuickSell(row) {
  const r = buildQuickOrder(row, 'sell', quickPct.value, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 卖 ${r.qty} 股 (${r.label})`,
    '一键卖出', { confirmButtonText: '确认卖出', cancelButtonText: '取消', type: 'warning' }
  ).then(() => submitOrder({ orderType: '24', volume: r.qty, price: r.price, taskId: selectedTaskId.value }))
    .catch(() => {})
}
function onQuickBalance(row) {
  const bal = getBalanceQty(row)
  if (bal === null) return ElMessage.warning('已配平, 无需操作')
  const side = _rowBalance(row).side
  // v54 Q3: 配平价格 = 对手盘价 (买→ask1 / 卖→bid1)
  const quote = quoteStore.get(row.stock_code)
  const { price: balancePrice, fallback } = resolveBalancePrice({ stock_code: row.stock_code }, side, quote)
  if (fallback) ElMessage.warning(`${row.stock_code} 对手盘价无效, 回退最新价 ¥${formatPriceAuto(balancePrice)}`)
  if (!selectedTaskId.value) {
    ElMessage.warning('未选 task，配平操作不会被归类。建议先在上方选 task。')
  }
  ElMessageBox.confirm(
    `${row.stock_code} ${side === 'buy' ? '买入' : '卖出'} ${bal} 股 配平 (净额归零, ${fallback ? '回退最新价' : '对手盘价'})`,
    '一键配平', { confirmButtonText: '确认配平', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: side === 'buy' ? '23' : '24', volume: bal, price: balancePrice, taskId: selectedTaskId.value }))
    .catch(() => {})
}

// ---- 快捷键 ----
useT0Keybindings({
  isEnabled: () => uiStore.t0Keybindings && !drawerVisible.value,
  onBuy: () => { const r = _selectedRow(); if (r && !buyState(r).disabled) onQuickBuy(r) },
  onSell: () => { const r = _selectedRow(); if (r && !sellState(r).disabled) onQuickSell(r) },
  onBalance: () => { const r = _selectedRow(); if (r && !balanceState(r).disabled) onQuickBalance(r) },
  onSelectPrev: () => _moveSelection(-1),
  onSelectNext: () => _moveSelection(1),
  onEnter: () => { const r = _selectedRow(); if (r) onOpenDrawer(r) },
})

// ---- 初始化 ----
onMounted(async () => {
  await loadAllT0Stats()
  t0TasksStore.loadTasks().catch(() => {})
  if (!stockCode.value && holdingsPositions.value.length > 0) {
    stockCode.value = holdingsPositions.value[0].stock_code
  }
})

// 持仓变化 → 差量补 stats
watch(() => holdingsPositions.value.map(p => p.stock_code), async (newCodes, oldCodes) => {
  if (!oldCodes) return
  await loadDiffT0Stats(newCodes, oldCodes)
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
.t0-task-quick-select {
  width: 180px;
}

/* 主表 — 11 列 */
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
.position-table :deep(tr.is-focused td) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}

/* 操作列 */
.op-col {
  display: flex;
  gap: 4px;
  align-items: center;
  justify-content: center;
  flex-wrap: nowrap;
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

/* quota 单元格颜色 (复用 v53 quotaLevel) */
.quota-cell { font-weight: 600; }
.quota-high { color: #67c23a; }
.quota-mid  { color: #e6a23c; }
.quota-low  { color: #f56c6c; }
.quota-none { color: var(--el-color-info); }

/* 颜色 */
.up { color: #f56c6c; }
.down { color: #67c23a; }
.muted { color: var(--el-color-info); }
.text-mono { font-family: var(--mono-font); }

/* 移动端 */
@media (max-width: 1100px) {
  .t0-task-quick-select {
    width: 140px;
  }
}
@media (max-width: 768px) {
  .t0-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .position-table {
    font-size: 12px;
  }
}
</style>
