<!--
  PositionTable.vue — 持仓表格 (统一 DataTableView)

  Props:
    - positions: Array — 持仓数据
    - loading: Boolean — 加载状态
    - selected: String — 选中的 stock_code
  Events:
    - @select — 行点击，传 stock_code
-->
<template>
  <div class="position-table-wrap">
    <DataTableView
      :columns="positionColumns"
      :data="positions"
      :loading="loading"
      :row-class-name="rowClassName"
      :default-sort="{ prop: 'vol', order: 'descending' }"
      :empty-description="'暂无持仓'"
      @row-click="handleRowClick"
      v-bind="$attrs"
    >
      <template #column-stock_code="{ row }">
        <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
        <span class="text-secondary" style="margin-left: 6px" v-t0-badge="row.stock_code">{{ row.stock_name || '—' }}</span>
      </template>

      <template #column-last_vol="{ row }">
        <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
      </template>

      <template #column-avl_vol="{ row }">
        <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
      </template>

      <template #column-vol="{ row }">
        <span class="text-mono total-cell">{{ formatNumber(row.vol) }}</span>
      </template>

      <template #column-ratio="{ row }">
        <div class="ratio-bar-wrap">
          <div class="ratio-bar">
            <div class="ratio-fill" :style="{ width: getRatio(row) + '%' }"></div>
          </div>
          <span class="ratio-text text-mono">{{ getRatio(row) }}%</span>
        </div>
      </template>

      <template #column-action="{ row }">
        <el-button link type="primary" size="small" @click.stop="handleRowClick(row)">
          明细
        </el-button>
      </template>
    </DataTableView>
  </div>
</template>

<script setup>
import DataTableView from './DataTableView.vue'
import { formatNumber } from '../utils/format'
import { COL } from '../utils/tableColumns'

const props = defineProps({
  positions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  selected: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const positionColumns = [
  { key: '__index__', label: '#', width: 50, align: 'center', sortable: false },
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'last_vol', label: '期初', vBind: COL.NUMBER },
  { key: 'avl_vol', label: '可用', vBind: COL.NUMBER },
  { key: 'vol', label: '总持仓', vBind: COL.NUMBER },
  { key: 'ratio', label: '可用占比', width: 120, align: 'left', sortable: false },
  { key: 'action', label: '操作', width: 120, fixed: 'right', align: 'center', sortable: false },
]

function handleRowClick(row) {
  emit('select', row.stock_code)
}

function rowClassName({ row }) {
  return props.selected === row.stock_code ? 'row-selected' : ''
}

function getRatio(row) {
  if (!row.vol) return 0
  return Math.round((row.avl_vol / row.vol) * 100)
}
</script>

<style scoped>
.position-table-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.total-cell {
  font-weight: 600;
  color: var(--brand-primary);
}

.ratio-bar-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.ratio-bar {
  flex: 1;
  height: 6px;
  background: var(--bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
  min-width: 60px;
}

.ratio-fill {
  height: 100%;
  background: var(--brand-gradient);
  border-radius: var(--radius-full);
  transition: width 400ms;
}

.ratio-text {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 40px;
  text-align: right;
}

:deep(.row-selected) {
  background: var(--brand-gradient-soft) !important;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
