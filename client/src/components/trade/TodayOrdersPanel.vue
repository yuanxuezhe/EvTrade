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

    <!-- tab=委托: 委托表格 + 撤单按钮 -->
    <div v-show="activeTab === 'orders'" class="tp-body">
      <el-table
        :data="pagedOrders"
        :show-overflow-tooltip="true"
        stripe
        size="small"
        class="tp-table"
      >
        <el-table-column prop="order_no" label="委托编号" width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_time" label="时间" width="100">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="代码" width="100">
          <template #default="{ row }">
            <span class="tp-stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_name" label="名称" width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-secondary">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="100">
          <template #default="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="委托量" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_volume" label="成交量" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" align="right" width="100">
          <template #default="{ row }">
            <span class="text-mono">¥{{ formatMoney(orderAmount(row)) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canCancel(row)"
              link
              type="danger"
              size="small"
              :loading="orderStore.cancelling && cancellingOrderNo === row.order_no"
              @click="handleCancel(row)"
            >
              撤
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日委托" :image-size="80" />
        </template>
      </el-table>
    </div>

    <!-- 分页: 行数 > pageSize 时显示 (避免行数少时的视觉噪声) -->
    <div v-if="activeTab === 'orders' && todayOrders.length > pageSize" class="tp-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="todayOrders.length"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        small
        background
        @current-change="onPageChange"
      />
    </div>

    <!-- v30.1: tab=成交 表格 (从 TodayTradesPanel v13.2 内嵌) -->
    <div v-show="activeTab === 'trades'" class="tp-body">
      <el-table
        :data="pagedTrades"
        :show-overflow-tooltip="true"
        stripe
        size="small"
        class="tp-table"
      >
        <el-table-column prop="trade_time" label="时间" width="100">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_time }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_id" label="成交编号" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trade_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="Number(row.trade_type) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">成交</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="代码" width="100">
          <template #default="{ row }">
            <span class="tp-stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_name" label="名称" width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-secondary">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="100">
          <template #default="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="量" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价" align="right" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" align="right" min-width="100">
          <template #default="{ row }">
            <span class="text-mono">¥{{ formatMoney(localAmount(row)) }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无当日成交" :image-size="80" />
        </template>
      </el-table>
    </div>

    <!-- v30.1: 成交 tab 分页 (条件: trade tab + 行数 > pageSize) -->
    <div v-if="activeTab === 'trades' && todayTrades.length > pageSize" class="tp-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="todayTrades.length"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        small
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
import { computed, nextTick, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatMoney, formatNumber } from '../../utils/format'
import { stockName } from '../../utils/stockNames'
import OrderStatusBadge from '../OrderStatusBadge.vue'
import { useHoldingsStore } from '../../stores/holdings'
import { useOrderStore } from '../../stores/order'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()

// v30.1: panel-local tab state, 默认 'orders' (委托查询)
const activeTab = ref('orders')

// 当日委托: trd_date === activeTrdDate + 排除 cancel-row (volume=0 会污染统计口径)
const todayOrders = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.orders.filter(
    (o) => o.trd_date === day && Number(o.order_flag) !== 1
  )
})

// v30.1: 当日成交: trd_date === activeTrdDate + 排除 cancel-fill (trade_type=1)
const todayTrades = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.trades.filter(
    (t) => t.trd_date === day && Number(t.trade_type) !== 1
  )
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

// 可撤状态: 非撤单审计 + 状态不在终态集
const TERMINAL_STATUSES = new Set(['51', '52', '53', '54', '55', '56', '57'])
function canCancel(row) {
  if (Number(row.order_flag) === 1) return false
  return !TERMINAL_STATUSES.has(String(row.status))
}

async function handleCancel(row) {
  try {
    await ElMessageBox.confirm(
      `确认撤销 ${row.stock_code} 委托 ${row.volume}@${formatMoney(row.price)}？`,
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
  overflow: auto;
  padding: 0 var(--space-3);
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
