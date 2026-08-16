<!--
  TodayOrdersPanel.vue — 今日委托 / 今日成交 双 tab mini 面板 (统一 DataTableView)

  v30.1 tab 修复 + DataTableView 迁移:
    tab=委托 (orders) — DataTableView + 撤单按钮
    tab=成交 (trades) — DataTableView + 金额本地计算
-->
<template>
  <div class="tp-shell content-card">
    <div class="tp-header tp-header--tabs">
      <el-tabs v-model="activeTab" class="tp-tabs">
        <el-tab-pane name="orders" :label="`今日委托 (${todayOrdersBase.length})`" />
        <el-tab-pane name="trades" :label="`今日成交 (${todayTradesBase.length})`" />
      </el-tabs>
    </div>

    <div v-if="activeTab === 'orders'" class="tp-body">
      <template v-if="idbSyncStatus?.orders !== 'syncing'">
        <DataTableView
          :columns="orderColumns"
          :data="todayOrdersBase"
          :default-sort="{ prop: 'order_time', order: 'descending' }"
          :empty-description="'暂无当日委托'"
          ref="ordersTableRef"
          @row-click="onRowClick"
          @row-dblclick="onRowDblclick"
        >
          <template #column-trd_date="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
          <template #column-order_no="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
          <template #column-type="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
          <template #column-stock_code="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px" v-t0-badge="row.stock_code">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
          <template #column-direction="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
          <template #column-volume="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
          <template #column-price_type="{ row }">
            <span class="text-secondary">{{ priceTypeLabel(row.price_type) || '—' }}</span>
          </template>
          <template #column-price="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
          <template #column-traded_volume="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
          </template>
          <template #column-avg_price="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatPrice(row.avg_price, row.stock_code) : '—' }}</span>
          </template>
          <template #column-traded_amount="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatMoney(row.traded_amount) : '—' }}</span>
          </template>
          <template #column-cancelled_volume="{ row }">
            <span class="text-mono">{{ formatNumber(row.cancelled_volume || 0) }}</span>
          </template>
          <template #column-order_id="{ row }">
            <span class="text-mono text-secondary">{{ row.order_id || '—' }}</span>
          </template>
          <template #column-status="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
          <template #column-action="{ row }">
            <el-button
              v-if="canCancel(row)"
              type="danger"
              size="small"
              :loading="orderStore.cancelling && cancellingOrderNo === row.order_no"
              @click.stop="handleCancel(row)"
            >撤单</el-button>
          </template>
          <template #column-order_time="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </DataTableView>
      </template>
    </div>

    <div v-if="activeTab === 'trades'" class="tp-body">
      <template v-if="idbSyncStatus?.trades !== 'syncing'">
        <DataTableView
          :columns="tradeColumns"
          :data="todayTradesBase"
          :default-sort="{ prop: 'trade_time', order: 'descending' }"
          :empty-description="'暂无当日成交'"
          ref="tradesTableRef"
          @row-click="onRowClick"
          @row-dblclick="onRowDblclick"
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
            <span class="text-secondary" style="margin-left: 6px" v-t0-badge="row.stock_code">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
          <template #column-direction="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
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
            <span class="text-mono">{{ formatMoney(localAmount(row)) }}</span>
          </template>
          <template #column-trade_id="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_id }}</span>
          </template>
          <template #column-trade_time="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_time }}</span>
          </template>
        </DataTableView>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DataTableView from '../DataTableView.vue'
import { formatMoney, formatNumber, priceTypeLabel } from '../../utils/format'
import { formatPrice } from '../../composables/usePricePrecision'
import { stockName } from '../../utils/stockNames'
import { COL } from '../../utils/tableColumns'
import OrderStatusBadge from '../OrderStatusBadge.vue'
import { useHoldingsStore } from '../../stores/holdings'
import { useOrderStore } from '../../stores/order'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()
const emit = defineEmits(['apply-to-order'])

let lastDblclickTs = 0
function onRowClick(row) {
  if (!row || !row.stock_code) return
  if (Date.now() - lastDblclickTs < 300) return
}
function onRowDblclick(row) {
  if (!row || !row.stock_code) return
  emit('apply-to-order', { stock_code: row.stock_code, stock_name: stockName(row.stock_code) || '' })
  lastDblclickTs = Date.now()
}

const idbSyncStatus = computed(() => holdingsStore.idbSyncStatus || {})

const activeTab = ref('orders')
const ordersTableRef = ref()
const tradesTableRef = ref()
watch(activeTab, async () => {
  await nextTick()
  // DataTableView 内部 el-table 重算
})

// 当日委托: trd_date === activeTrdDate + 排除 cancel-row
const todayOrdersBase = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.orders
    .filter((o) => o.trd_date === day && Number(o.order_flag) !== 1)
})

// 当日成交: trd_date === activeTrdDate + 排除 cancel-fill
const todayTradesBase = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.trades
    .filter((t) => t.trd_date === day && Number(t.trade_type) !== 1)
})

const cancellingOrderNo = ref('')
const CANCELLABLE_STATUSES = new Set(['50', '55'])
function canCancel(row) {
  if (Number(row.order_flag) === 1) return false
  return CANCELLABLE_STATUSES.has(String(row.status))
}

async function handleCancel(row) {
  try {
    await ElMessageBox.confirm(
      `确认撤销 ${row.stock_code} 委托 ${row.volume}@${formatPrice(row.price, row.stock_code)}？`,
      '撤单确认',
      { confirmButtonText: '确认撤单', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  cancellingOrderNo.value = row.order_no
  try {
    await orderStore.cancelOrder(row.order_no, row.trd_date)
    ElMessage.success('已发送撤单请求, 等待 broker 回报')
  } catch (e) { /* 错误已由 axios 拦截器弹 ElMessage.error */ } finally {
    cancellingOrderNo.value = ''
  }
}

function localAmount(t) {
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

// 列定义
const orderColumns = [
  { key: 'trd_date', label: '交易日', vBind: COL.TRD_DATE },
  { key: 'order_no', label: '委托编号', vBind: COL.SHORT_SNO },
  { key: 'type', label: '类型', width: 100, sortable: false },
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'direction', label: '方向', vBind: COL.DIRECTION, sortable: false },
  { key: 'volume', label: '委托量', vBind: COL.NUMBER },
  { key: 'price_type', label: '价格类型', vBind: COL.PRICE_TYPE },
  { key: 'price', label: '委托价', vBind: COL.PRICE },
  { key: 'traded_volume', label: '成交量', vBind: COL.NUMBER },
  { key: 'avg_price', label: '成交均价', vBind: COL.PRICE },
  { key: 'traded_amount', label: '成交金额', vBind: COL.MONEY, sortable: false },
  { key: 'cancelled_volume', label: '撤单量', vBind: COL.NUMBER },
  { key: 'order_id', label: '合同序号', vBind: COL.SHORT_SNO },
  { key: 'status', label: '状态', vBind: COL.STATUS },
  { key: 'action', label: '操作', width: 100, fixed: 'right', align: 'center', sortable: false },
  { key: 'order_time', label: '下单时间', vBind: COL.TIME },
]

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
.tp-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.tp-header--tabs {
  padding: 0 var(--space-3, 8px);
  border-bottom: 1px solid var(--border-light, #ebeef5);
  flex-shrink: 0;
}
.tp-tabs {
  width: 100%;
}
:deep(.tp-tabs .el-tabs__header) {
  margin: 0;
}
:deep(.tp-tabs .el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border-light, #ebeef5);
}
:deep(.tp-tabs .el-tabs__item) {
  font-size: 13px;
  font-weight: 500;
  padding: 0 14px;
  height: 38px;
  line-height: 38px;
}

.tp-body {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

.tp-stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
}

:deep(.el-table__row) {
  cursor: pointer;
}
:deep(.el-table__row:hover > td.el-table__cell) {
  background-color: var(--bg-hover) !important;
}

.tp-dir-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 8px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
}
.tp-dir-chip.buy { background: var(--color-up-bg); color: var(--color-up); }
.tp-dir-chip.sell { background: var(--color-down-bg); color: var(--color-down); }
</style>
