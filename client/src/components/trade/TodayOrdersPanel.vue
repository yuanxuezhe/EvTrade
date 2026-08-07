<!--
  TodayOrdersPanel.vue — 今日委托 / 今日成交 双 tab mini 面板 (v30.1 tab 修复)

  v30.1 修复:
    之前 v30 整体布局重构误把 TodayTradesPanel 砍掉, 改回 panel 内嵌 el-tabs 双 tab:
      tab=委托 (orders)  默认显示, 显示今日委托表格 + 撤单按钮
      tab=成交 (trades)  显示今日成交表格 + 金额本地计算
    tab 切换由 panel-local state activeTab 驱动, 不入 Pinia / IDB

  数据契约 (与 TodayTradesPanel 对称):
    - useHoldingsStore().orders / trades (Pinia 内存 + IDB write-through)
    - 范围过滤 (panel-local computed): trd_date === activeDay + 排除 cancel-fill
    - 分页: panel-local state, 不入 Pinia / IDB

  历史:
    v30.1 双 tab 合并 (委托/成交) + 修复 v30 tab 丢失
    v13.2 分页版 (单 panel 委托)
    v13   嵌入 Trade.vue 右栏
-->
<template>
  <div class="tp-shell content-card">
    <div class="tp-header tp-header--tabs">
      <el-tabs v-model="activeTab" class="tp-tabs">
        <el-tab-pane name="orders" :label="`今日委托 (${todayOrders.length})`" />
        <el-tab-pane name="trades" :label="`今日成交 (${todayTrades.length})`" />
      </el-tabs>
    </div>

    <!--
      列顺序:
        交易日 → 委托编号 → 类型 → 标的 → 方向 → 委托量/价/成交量/均价/金额/撤单量 → 状态 → 操作 → 下单时间
      v69 接入: 表格列宽/对齐走 utils/tableColumns.js COL 常量, 业务 prop/label 保留
      隐藏: T0任务/策略 (T0Trade.vue 内嵌面板仍可见)
      下单时间 width=185: 容纳 String(23) "YYYY-MM-DD HH:MM:SS.fff" 全显
      :default-sort order_time descending: 最新在下, 与 HistoryOrders 一致
      v75: 成交 tab 9→8 列: 代码+名称合并成标的(v68 风格); 量→成交量; 价→成交价; 接入 COL 常量
    -->
    <div v-if="activeTab === 'orders'" class="tp-body">
      <template v-if="idbSyncStatus?.orders !== 'syncing'">
      <el-table
        ref="ordersTableRef"
        :data="pagedOrders"
        :show-overflow-tooltip="true"
        height="100%"
        stripe
        size="small"
        class="tp-table"
        :default-sort="{ prop: 'order_time', order: 'descending' }"
      >
        <el-table-column prop="trd_date" label="交易日" sortable v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
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
        <el-table-column prop="stock_code" label="标的" sortable show-overflow-tooltip v-bind="COL.STOCK_TARGET">
          <template #default="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" v-bind="COL.DIRECTION">
          <template #default="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
        </el-table-column>
        <!-- v58 fix: 委托表列改 - 委托价 + 委托量/成交量/均价/金额/撤单量 分列 -->
        <el-table-column prop="volume" label="委托量" sortable v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="委托价" sortable v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_volume" label="成交量" sortable v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_price" label="成交均价" sortable v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatPrice(row.avg_price, row.stock_code) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成交金额" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatMoney(row.traded_amount) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cancelled_volume" label="撤单量" sortable v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.cancelled_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" v-bind="COL.STATUS">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canCancel(row)"
              type="danger"
              size="small"
              :loading="orderStore.cancelling && cancellingOrderNo === row.order_no"
              @click="handleCancel(row)"
            >
              撤单
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="order_time" label="下单时间" sortable v-bind="COL.TIME">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日委托" :image-size="80" />
        </template>
      </el-table>
      </template>
    </div>

    <!-- 分页: 行数 > pageSize 时显示 (避免行数少时的视觉噪声) -->
    <div v-if="activeTab === 'orders' && todayOrders.length > pageSize" class="tp-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="todayOrders.length"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        size="small"
        background
        @current-change="onPageChange"
      />
    </div>

    <!-- change 2026-07-21-trades-tab-column-reorder: 列序对齐委托 tab — 交易日/委托编号.../时间(最后) -->
    <div v-if="activeTab === 'trades'" class="tp-body">
      <template v-if="idbSyncStatus?.trades !== 'syncing'">
      <el-table
        ref="tradesTableRef"
        :data="pagedTrades"
        :show-overflow-tooltip="true"
        height="100%"
        stripe
        size="small"
        class="tp-table"
      >
        <el-table-column prop="trd_date" label="交易日" sortable v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="委托编号" show-overflow-tooltip v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">成交</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="标的" sortable show-overflow-tooltip v-bind="COL.STOCK_TARGET">
          <template #default="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" v-bind="COL.DIRECTION">
          <template #default="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="成交量" sortable v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="成交价" sortable v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(localAmount(row)) }}</span>
          </template>
        </el-table-column>
        <!-- change 2026-07-21-trades-tab-column-reorder: 时间挪到最后一列 -->
        <el-table-column prop="trade_time" label="时间" sortable v-bind="COL.TIME">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_time }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日成交" :image-size="80" />
        </template>
      </el-table>
      </template>
    </div>

    <!-- v30.1: 成交 tab 分页 (条件: trade tab + 行数 > pageSize) -->
    <div v-if="activeTab === 'trades' && todayTrades.length > pageSize" class="tp-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="todayTrades.length"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        size="small"
        background
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

<script setup>
/**
 * TodayOrdersPanel.vue — 今日委托/成交 mini 面板 (v30.1 双 tab 合并)
 *
 * 数据契约:
 *   - useHoldingsStore().orders (Pinia 内存 + IDB write-through)
 *   - useHoldingsStore().trades (Pinia 内存 + IDB write-through)
 *   - 范围过滤 (panel-local computed): trd_date === activeDay + 排除 cancel-fill
 *   - 分页: panel-local state, 不入 Pinia / IDB
 *   - 撤单: canCancel(row) 守卫限于 activeDay + 非终态 + 非 cancel-row
 *
 * v30.1:
 *   - 加 activeTab panel-local state, 默认 'orders'
 *   - 内嵌 trade 表格 (原 TodayTradesPanel 逻辑)
 *   - 标题: tab=委托→"今日委托 N 笔" / tab=成交→"今日成交 N 笔"
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatMoney, formatNumber } from '../../utils/format'
import { formatPrice } from '../../composables/usePricePrecision'
import { stockName } from '../../utils/stockNames'
import { COL } from '../../utils/tableColumns'
import OrderStatusBadge from '../OrderStatusBadge.vue'
import { useHoldingsStore } from '../../stores/holdings'
import { useOrderStore } from '../../stores/order'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()
const idbSyncStatus = computed(() => holdingsStore.idbSyncStatus || {})

// v30.1: panel-local tab state, 默认 'orders' (委托查询)
const activeTab = ref('orders')

// v59: tab 切换后触发 el-table 重算 layout (rows offsetHeight=0 修复)
const ordersTableRef = ref()
const tradesTableRef = ref()
watch(activeTab, async () => {
  await nextTick()
  const ref = activeTab.value === 'orders' ? ordersTableRef.value : tradesTableRef.value
  ref?.doLayout?.()
})

// 当日委托: trd_date === activeTrdDate + 排除 cancel-row (volume=0 会污染统计口径)
// v90: 按 order_time 倒序 (最新在上), 数据层排序保证分页/新增推送都在顶部
const todayOrders = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.orders
    .filter((o) => o.trd_date === day && Number(o.order_flag) !== 1)
    .sort((a, b) => (b.order_time || '').localeCompare(a.order_time || ''))
})

// v30.1: 当日成交: trd_date === activeTrdDate + 排除 cancel-fill (trade_type=1)
// v90: 按 trade_time 倒序 (最新在上)
const todayTrades = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.trades
    .filter((t) => t.trd_date === day && Number(t.trade_type) !== 1)
    .sort((a, b) => (b.trade_time || '').localeCompare(a.trade_time || ''))
})

// 分页 (panel-local state)
const page = ref(1)
const pageSize = ref(20)
const pagedOrders = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return todayOrders.value.slice(start, start + pageSize.value)
})
const pagedTrades = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return todayTrades.value.slice(start, start + pageSize.value)
})

const cancellingOrderNo = ref('')

// v91: 可撤状态白名单 - 仅 已报(50) / 部成(55) 可撤
//   48/49 (未报/待报) broker order_id 未回报, 不可撤; 51/52 已在撤单流程中; 53/54/56/57 终态
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
      {
        confirmButtonText: '确认撤单',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  cancellingOrderNo.value = row.order_no
  try {
    await orderStore.cancelOrder(row.order_no, row.trd_date)
    ElMessage.success('已发送撤单请求, 等待 broker 回报')
  } catch (e) {
    // 错误已由 axios 拦截器弹 ElMessage.error
  } finally {
    cancellingOrderNo.value = ''
  }
}

// 本地算 amount (委托: price × traded_volume, 成交: price × volume), 与后端 trd_cfm 公式一致
function orderAmount(o) {
  return (Number(o.price) || 0) * (Number(o.traded_volume ?? o.volume) || 0)
}
function localAmount(t) {
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

// 翻页后 el-table 滚动条归顶 (翻页体验更自然)
function onPageChange() {
  nextTick(() => {
    const wrap = document.querySelector('.tp-table .el-scrollbar__wrap')
    if (wrap) wrap.scrollTop = 0
  })
}
</script>

<style scoped>
.tp-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.tp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}

/* v30.1: tab 模式 header — 去 padding 让 el-tabs 紧贴边界 */
.tp-header--tabs {
  padding: 0 var(--space-3);
}
.tp-tabs {
  width: 100%;
}
:deep(.tp-tabs .el-tabs__header) {
  margin: 0;
}
:deep(.tp-tabs .el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border-light);
}
:deep(.tp-tabs .el-tabs__item) {
  font-size: 13px;
  font-weight: 500;
  padding: 0 14px;
  height: 38px;
  line-height: 38px;
}

.tp-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}

.tp-count {
  font-size: 12px;
  color: var(--text-secondary);
}

.tp-body {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
  padding: 0 var(--space-3);
}

/* v59: el-table 占满 .tp-body 高度, 激活内部垂直滚动条 (与 Dashboard 持仓查询 .panel :deep(.el-table) 一致)
   之前 el-table 高度 = 内容撑高, 数据多时撑出 panel 被 .tp-shell overflow:hidden 裁切
   现在 .tp-table height:100% → el-table__body-wrapper 继承高度 → 行数>可视区时自动出垂直滚动条
   scoped 隔离: 仅 TodayOrdersPanel 内 .tp-table 生效, 不污染其他 el-table */
:deep(.tp-body .el-table) {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}
:deep(.tp-body .el-table .el-table__body-wrapper) {
  flex: 1 1 0;
  min-height: 0;
  /* Element Plus el-table body-wrapper 默认 overflow-y: hidden + max-height 由父算, 此处强制激活垂直滚动 */
  overflow-y: auto;
}

.tp-table {
  width: 100%;
}

.tp-stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
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

.tp-pagination {
  display: flex;
  justify-content: flex-end;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border-light);
  flex-shrink: 0;
}
</style>
