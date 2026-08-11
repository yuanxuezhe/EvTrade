<!--
  BatchTasksTable.vue — 批次内任务表格 (v123, 替代旧 SweepResultsTable)

  前几列 = 参数动态列 (来自策略脚本 params_schema key), 后几列 = 结果列。
  Props:
    - tasks: Array<task dict>  批次内任务 (listBatchTasks 返回)
    - schema: Array<{key, ...}> 脚本 params_schema (决定参数列顺序)
    - selectedId: Number        高亮当前选中任务
  Emits:
    - select(task) 点击任务行
-->
<template>
  <el-table
    :data="tasks"
    size="small"
    border
    stripe
    highlight-current-row
    :row-key="(row) => row.id"
    :current-row-key="selectedId"
    max-height="340"
    @row-click="$emit('select', $event)"
    data-el="batch-tasks-table"
  >
    <el-table-column label="ID" prop="id" width="60" />
    <el-table-column
      v-for="k in paramKeys"
      :key="'p-' + k"
      :label="k"
      min-width="90"
      show-overflow-tooltip
    >
      <template #default="{ row }">
        <span>{{ _paramValue(row, k) }}</span>
      </template>
    </el-table-column>

    <el-table-column label="状态" width="90">
      <template #default="{ row }">
        <el-tag size="small" :type="_statusType(row.status)">{{ _statusLabel(row.status) }}</el-tag>
      </template>
    </el-table-column>

    <el-table-column label="PnL" width="90" align="right">
      <template #default="{ row }">
        <span v-if="row.pnl !== undefined && row.status === 'finished'"
              :class="row.pnl > 0 ? 'up' : row.pnl < 0 ? 'down' : ''">
          {{ Number(row.pnl).toFixed(2) }}
        </span>
        <span v-else class="bf-muted">—</span>
      </template>
    </el-table-column>

    <el-table-column label="指标" width="100" align="right">
      <template #default="{ row }">
        <span v-if="row.backtest_metric_value !== null && row.backtest_metric_value !== undefined"
              :class="_metricClass(row.backtest_metric_value)">
          {{ Number(row.backtest_metric_value).toFixed(4) }}
        </span>
        <span v-else class="bf-muted">—</span>
      </template>
    </el-table-column>

    <el-table-column label="成交笔数" prop="trades_count" width="80" align="right" />

    <el-table-column label="回测区间" width="170">
      <template #default="{ row }">
        <span v-if="row.backtest_start_date" class="bf-muted">
          {{ row.backtest_start_date }} ~ {{ row.backtest_end_date }}
        </span>
        <span v-else class="bf-muted">—</span>
      </template>
    </el-table-column>

    <el-table-column label="错误" min-width="120" show-overflow-tooltip>
      <template #default="{ row }">
        <span v-if="row.error_msg" class="bf-error">{{ row.error_msg }}</span>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  schema: { type: Array, default: () => [] },
  selectedId: { type: Number, default: null },
})
defineEmits(['select'])

// 参数列: schema key 优先; schema 为空时取所有 task params 的 key 并集 (按出现顺序)
const paramKeys = computed(() => {
  const schemaKeys = (props.schema || []).map((s) => s.key).filter(Boolean)
  if (schemaKeys.length) return schemaKeys
  const seen = []
  for (const t of props.tasks) {
    for (const k of Object.keys(t.params || {})) {
      if (!seen.includes(k)) seen.push(k)
    }
  }
  return seen
})

function _paramValue(row, key) {
  const v = row.params?.[key]
  if (v === undefined || v === null) return '—'
  return typeof v === 'number' ? String(v) : v
}

function _statusType(s) {
  return {
    queued: 'info',
    running: 'warning',
    finished: 'success',
    failed: 'danger',
    stopped: 'primary',
    abandoned: 'info',
  }[s] || 'primary'
}
function _statusLabel(s) {
  return {
    queued: '排队中',
    running: '运行中',
    finished: '完成',
    failed: '失败',
    stopped: '已停',
    abandoned: '已废弃',
  }[s] || (s || '—')
}

function _metricClass(v) {
  if (v === null || v === undefined) return ''
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}
</script>

<style scoped>
.up { color: var(--color-up, #f56c6c); font-weight: 600; }
.down { color: var(--color-down, #67c23a); font-weight: 600; }
.bf-muted { color: var(--text-placeholder); }
.bf-error { color: var(--color-down, #f56c6c); font-size: 12px; }
</style>
