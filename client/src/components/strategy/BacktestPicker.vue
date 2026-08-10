<!--
  BacktestPicker.vue — 历史回测选择器 (script-strategy v122+)

  职责: 列某脚本历史 backtest (含 sweep summary), 点选返 best_params 供 live 启参。
  Props:
    - scriptId: String  限定脚本
    - modelValue: Boolean  dialog 显隐
  Emits:
    - update:modelValue(Boolean)  关闭
    - select({task_id, best_params, mode, sweep_id, backtest_metric_value})  点选某行
-->
<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    :title="`选择历史回测 — ${scriptName}`"
    width="780px"
    append-to-body
    data-el="backtest-picker"
  >
    <div v-loading="loading" class="bp-wrap">
      <div class="bp-toolbar">
        <span class="bp-hint">点选一行 → 自动填入最优参数到启实盘表单</span>
        <el-button :icon="Refresh" size="small" link @click="load" data-el="bp-refresh">刷新</el-button>
      </div>

      <el-table
        :data="rows"
        size="small"
        border
        highlight-current-row
        @row-click="onRowClick"
        data-el="bp-table"
      >
        <el-table-column label="ID" prop="id" width="60" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.sweep_id" size="small" type="success" effect="dark">
              扫描 {{ row.sweep_total }} 组
            </el-tag>
            <el-tag v-else size="small" type="info" effect="plain">单 run</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="指标" width="120">
          <template #default="{ row }">
            <span :class="_metricClass(row.backtest_metric_value)">
              {{ _metricLabel(row.sweep_metric) }} {{ _formatMetric(row.backtest_metric_value) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最优参数" min-width="240">
          <template #default="{ row }">
            <div class="bp-params">
              <el-tag
                v-for="(v, k) in (row.best_params || {})"
                :key="k"
                size="small"
                effect="plain"
                type="info"
              >{{ k }}={{ v }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="完成时间" width="160">
          <template #default="{ row }">
            <span class="bp-time">{{ _fmtTime(row.finished_at) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && rows.length === 0" description="该脚本暂无历史回测" />
    </div>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { scriptStrategyApi } from '../../api/script_strategy'

const props = defineProps({
  scriptId: { type: String, default: '' },
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'select'])

const loading = ref(false)
const rows = ref([])
const scriptName = computed(() => props.scriptId || '—')

async function load() {
  if (!props.scriptId) {
    rows.value = []
    return
  }
  loading.value = true
  try {
    const data = await scriptStrategyApi.listFinishedBacktests({ scriptId: props.scriptId, limit: 50 })
    rows.value = data || []
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (v) => { if (v) load() })
watch(() => props.scriptId, () => { if (props.modelValue) load() })

function onRowClick(row) {
  emit('select', {
    task_id: row.id,
    best_params: row.best_params || {},
    mode: row.mode,
    sweep_id: row.sweep_id,
    backtest_metric_value: row.backtest_metric_value,
  })
  emit('update:modelValue', false)
}

function _metricLabel(m) {
  return ({ sharpe: 'Sharpe', total_return: '收益', calmar: 'Calmar' })[m] || (m || 'metric')
}

function _formatMetric(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v !== 'number') return String(v)
  return v.toFixed(4)
}

function _metricClass(v) {
  if (v === null || v === undefined) return ''
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return ''
}

function _fmtTime(s) {
  if (!s) return '—'
  return s.length > 16 ? s.slice(5, 16).replace('T', ' ') : s
}
</script>

<style scoped>
.bp-wrap { min-height: 200px; }
.bp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.bp-hint { color: #909399; font-size: 13px; }
.bp-params { display: flex; flex-wrap: wrap; gap: 4px; }
.bp-time { color: #909399; font-size: 12px; }
.up { color: #67c23a; }
.down { color: #f56c6c; }
</style>