<template>
  <el-table
    :data="positions"
    v-loading="loading"
    highlight-current-row
    @row-click="handleRowClick"
    :row-class-name="rowClass"
    style="width: 100%"
    size="default"
  >
    <!-- v73: 7 列接入 COL 常量 -->
    <el-table-column type="index" label="#" width="50" align="center" />
    <el-table-column prop="stock_code" label="股票代码" v-bind="COL.makeDict('stock', { minWidth: 140 })">
      <template #default="{ row }">
        <div class="stock-cell">
          <div class="stock-code">{{ row.stock_code }}</div>
          <div class="stock-name">{{ row.stock_name || '--' }}</div>
        </div>
      </template>
    </el-table-column>
    <el-table-column prop="last_vol" label="期初" v-bind="COL.NUMBER">
      <template #default="{ row }">
        <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
      </template>
    </el-table-column>
    <el-table-column prop="avl_vol" label="可用" v-bind="COL.NUMBER">
      <template #default="{ row }">
        <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
      </template>
    </el-table-column>
    <el-table-column prop="vol" label="总持仓" v-bind="COL.NUMBER">
      <template #default="{ row }">
        <span class="text-mono total-cell">{{ formatNumber(row.vol) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="可用占比" width="120" align="left">
      <template #default="{ row }">
        <div class="ratio-bar-wrap">
          <div class="ratio-bar">
            <div class="ratio-fill" :style="{ width: getRatio(row) + '%' }"></div>
          </div>
          <span class="ratio-text text-mono">{{ getRatio(row) }}%</span>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="120" fixed="right" align="center">
      <template #default="{ row }">
        <el-button link type="primary" size="small" @click.stop="handleRowClick(row)">
          明细
        </el-button>
      </template>
    </el-table-column>
    <template #empty>
      <el-empty description="暂无持仓" :image-size="100" />
    </template>
  </el-table>
</template>

<script setup>
import { formatNumber } from '../utils/format'
import { COL } from '../utils/tableColumns'

const props = defineProps({
  positions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  selected: { type: String, default: '' }
})

const emit = defineEmits(['select'])

function handleRowClick(row) {
  emit('select', row.stock_code)
}

function rowClass({ row }) {
  return props.selected === row.stock_code ? 'row-selected' : ''
}

function getRatio(row) {
  if (!row.vol) return 0
  return Math.round((row.avl_vol / row.vol) * 100)
}
</script>

<style scoped>
.stock-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-primary);
  font-size: 13px;
}

.stock-name {
  font-size: 11px;
  color: var(--text-secondary);
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
