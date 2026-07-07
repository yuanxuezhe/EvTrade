<!--
  TodayOrdersPanel.vue — 今日委托 mini 面板 (v13.2 分页版)

  数据源: useHoldingsStore().orders (Pinia + IDB write-through)
  严格过滤: trd_date === activeTrdDate + exclude cancel-fill (order_flag=1)
  嵌在 Trade.vue 右侧 (与下单表单 + 委托面板同屏)
  click-to-cancel: 委托行点'撤' → ElMessageBox.confirm → orderStore.cancelOrder
  分页: el-pagination 默认 20 行/页, pageSizes [10,20,50,100]
       panel-local state, 不入 Pinia
-->
<template>
  <div class="tp-shell content-card">
    <div class="tp-header">
      <h3 class="tp-title">今日委托</h3>
      <span class="tp-count text-mono">{{ todayOrders.length }} 笔</span>
    </div>

    <div class="tp-body">
      <el-table
        :data="pagedOrders"
        :show-overflow-tooltip="true"
        stripe
        size="small"
        class="tp-table"
      >
        <el-table-column prop="order_no" label="委托编号" width="98" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_time" label="时间" width="78">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.order_time }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="60">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="代码" width="92">
          <template #default="{ row }">
            <span class="tp-stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="48">
          <template #default="{ row }">
            <span class="tp-dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="委托量" align="right" width="64" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_volume" label="成交量" align="right" width="64" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价" align="right" width="68" sortable>
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" align="right" width="92">
          <template #default="{ row }">
            <span class="text-mono">¥{{ formatMoney(orderAmount(row)) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="78">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :remark="row.remark" :status_msg="row.status_msg" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="48" fixed="right">
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
    <div v-if="todayOrders.length > pageSize" class="tp-pagination">
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
  </div>
</template>

<script setup>
/**
 * TodayOrdersPanel.vue — 今日委托 mini 面板 (v13.2)
 *
 * 数据契约:
 *   - useHoldingsStore().orders (Pinia 内存 + IDB write-through)
 *   - 范围过滤 (panel-local computed): trd_date === activeDay + order_flag !== 1
 *   - 分页: panel-local state, 不入 Pinia / IDB
 *   - 撤单: canCancel(row) 守卫限于 activeDay + 非终态 + 非 cancel-row
 */
import { computed, nextTick, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatMoney, formatNumber } from '../../utils/format'
import OrderStatusBadge from '../OrderStatusBadge.vue'
import { useHoldingsStore } from '../../stores/holdings'
import { useOrderStore } from '../../stores/order'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()

// 当日委托: trd_date === activeTrdDate + 排除 cancel-row (volume=0 会污染统计口径)
const todayOrders = computed(() => {
  const day = holdingsStore.activeTrdDate
  if (!day) return []
  return holdingsStore.orders.filter(
    (o) => o.trd_date === day && Number(o.order_flag) !== 1
  )
})

// 分页 (panel-local state)
const page = ref(1)
const pageSize = ref(20)
const pagedOrders = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return todayOrders.value.slice(start, start + pageSize.value)
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

// 本地算 amount (price × traded_volume), 与后端 trd_cfm 公式一致
function orderAmount(o) {
  return (Number(o.price) || 0) * (Number(o.traded_volume ?? o.volume) || 0)
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
