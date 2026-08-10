<!--
  SweepResultsTable.vue — Sweep summary 任务的结果展示 (script-strategy v122+)

  职责: 读 detail.backtest_result.sweep_results, 列每个组合的 params + metric_value + status。
  Props:
    - backtestResult: Object  strategy_task.backtest_result JSON
    - metric: String  排序指标名 (sharpe / total_return / calmar)
-->
<template>
  <div v-if="rows.length" class="srt-wrap" data-el="sweep-results-table">
    <h4 class="srt-title">参数扫描结果 ({{ rows.length }} 组)</h4>
    <el-table :data="rows" size="small" border max-height="400">
      <el-table-column label="排名" prop="rank" width="60" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'completed' ? 'success' : 'danger'">
            {{ row.status === 'completed' ? '完成' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="metricLabel" width="100">
        <template #default="{ row }">
          <span :class="_valueClass(row.metric_value)">{{ _formatValue(row.metric_value) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="参数" min-width="280">
        <template #default="{ row }">
          <div class="srt-params">
            <el-tag
              v-for="(v, k) in row.params"
              :key="k"
              size="small"
              effect="plain"
              type="info"
            >{{ k }}={{ v }}</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="PnL" width="100">
        <template #default="{ row }">
          <span :class="_valueClass(row.pnl)">{{ _formatValue(row.pnl) }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  backtestResult: { type: Object, default: () => null },
  metric: { type: String, default: 'sharpe' },
})

const rows = computed(() => {
  const r = props.backtestResult
  if (!r || !Array.isArray(r.sweep_results)) return []
  return r.sweep_results.map((item, i) => ({
    rank: i + 1,
    status: item.status || 'completed',
    metric_value: item.metric_value ?? null,
    params: item.params || {},
    pnl: item.pnl ?? null,
  }))
})

const metricLabel = computed(() => ({
  sharpe: 'Sharpe',
  total_return: '总收益',
  calmar: 'Calmar',
}[props.metric] || props.metric))

function _formatValue(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v !== 'number') return String(v)
  return v.toFixed(4)
}
function _valueClass(v) {
  if (v === null || v === undefined) return ''
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return ''
}
</script>

<style scoped>
.srt-wrap { margin-top: 16px; }
.srt-title { margin: 0 0 8px; }
.srt-params { display: flex; flex-wrap: wrap; gap: 4px; }
.up { color: #67c23a; }
.down { color: #f56c6c; }
</style>