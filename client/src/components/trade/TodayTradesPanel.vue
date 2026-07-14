<!--
  TodayTradesPanel.vue — 今日成交 mini 面板 (v13.2 分页版)

  数据源: useHoldingsStore().trades (Pinia + IDB write-through)
  严格过滤: trd_date === activeTrdDate + exclude cancel-fill (trade_type=1)
  嵌在 Trade.vue 右侧 (与下单表单 + 委托面板同屏)
  无撤单按钮 (trades 是终态历史, 不可撤)
  分页: el-pagination 默认 20 行/页, 与 TodayOrdersPanel 对称
-->
<template>
  <div class="tp-shell content-card">
    <div class="tp-header">
      <h3 class="tp-title">今日成交</h3>
      <span class="tp-count text-mono">{{ todayTrades.length }} 笔</span>
    </div>

    <div class="tp-body">
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

    <!-- 分页: 行数 > pageSize 时显示 -->
    <div v-if="todayTrades.length > pageSize" class="tp-pagination">
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
 * TodayTradesPanel.vue — 今日成交 mini 面板 (v13.2)
 *
 * 数据契约:
 *   - useHoldingsStore().trades (Pinia 内存 + IDB write-through)
 *   - 范围过滤 (panel-local computed): trd_date === activeDay + trade_type !== 1
 *   - 分页: panel-local state, 不入 Pinia / IDB
 *   - 无撤单按钮 (trades 是终态历史)
 */
import { computed, nextTick, ref } from 'vue'
import { formatMoney, formatNumber } from '../../utils/format'
import { stockName } from '../../utils/stockNames'
import { useHoldingsStore } from '../../stores/holdings'

const holdingsStore = useHoldingsStore()

// 当日成交: trd_date === activeTrdDate + 排除 cancel-fill (trade_type=1)
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
const pagedTrades = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return todayTrades.value.slice(start, start + pageSize.value)
})

// 本地算 amount (price × volume), 与后端 trd_cfm 公式一致
function localAmount(t) {
  return (Number(t.volume) || 0) * (Number(t.price) || 0)
}

// 翻页后 el-table 滚动条归顶
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
