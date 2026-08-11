<!--
  StrategyOrderChildren.vue — 策略母单子单 (v126, 子组件)

  选中母单 → 实时从 holdings.orders 过滤 strategy_type=2 + task_id=母单.task_id
  跟随 WS 推送 (holdings store 自动更新, computed 实时刷新)
-->
<template>
  <el-card shadow="never" class="so-children-card" data-el="so-children-card">
    <template #header>
      <div class="so-card-head">
        <span>委托子单</span>
        <span class="so-card-sub">
          {{ selectedOrder ? `${filtered.length} / ${total} 笔` : '请先选母单' }}
        </span>
      </div>
    </template>
    <el-table
      v-if="selectedOrder"
      :data="filtered"
      size="small"
      border
      stripe
      :row-key="(r) => `${r.trd_date}-${r.order_no}`"
      empty-text="暂无子单 (live 启动后 BUY/SELL 信号下出)"
      data-el="so-children-table"
      max-height="380"
    >
      <el-table-column label="时间" prop="order_time" width="100" />
      <el-table-column label="标的" prop="stock_code" width="100" />
      <el-table-column label="方向" width="60">
        <template #default="{ row }">
          <el-tag size="small" :type="row.order_type === '23' ? 'danger' : 'success'" effect="plain">
            {{ row.order_type === '23' ? '买' : '卖' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="价格" prop="price" width="80" />
      <el-table-column label="数量" prop="volume" width="70" />
      <el-table-column label="已成" prop="traded_volume" width="70" />
      <el-table-column label="状态" prop="status_msg" min-width="100" />
      <el-table-column label="备注" prop="user_def" min-width="100">
        <template #default="{ row }">
          <span class="so-user-def">{{ row.user_def }}</span>
        </template>
      </el-table-column>
    </el-table>
    <div v-else class="so-empty">先选中母单查看子单</div>
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '@/stores/holdings'

const props = defineProps({
  selectedOrder: { type: Object, default: null },
})

const holdings = useHoldingsStore()
const { orders: holdingsOrders } = storeToRefs(holdings)

const total = computed(() => {
  if (!props.selectedOrder) return 0
  const target = Number(props.selectedOrder.task_id)
  return holdingsOrders.value.filter(
    o => Number(o.task_id) === target && o.strategy_type === 2,
  ).length
})

const filtered = computed(() => {
  if (!props.selectedOrder) return []
  const target = Number(props.selectedOrder.task_id)
  return holdingsOrders.value
    .filter(o => Number(o.task_id) === target && o.strategy_type === 2)
    .slice()
    .sort((a, b) => String(b.order_time || '').localeCompare(String(a.order_time || '')))
})
</script>

<style scoped>
.so-user-def { font-family: var(--el-font-family-monospace, monospace); font-size: 12px; }
.so-empty { padding: 24px; text-align: center; color: var(--el-text-color-secondary); }
</style>
