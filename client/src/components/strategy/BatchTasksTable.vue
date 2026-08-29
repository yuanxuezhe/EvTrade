<!--
  BatchTasksTable.vue — 批次内任务表格 (替代旧 SweepResultsTable)

  前几列 = 参数动态列 (来自策略脚本 params_schema key), 后几列 = 结果列。
  Props:
    - tasks: Array<task dict>  批次内任务 (listBatchTasks 返回)
    - schema: Array<{key, ...}> 脚本 params_schema (决定参数列顺序)
    - selectedId: Number        高亮当前选中任务
    - showStaleOnly: Boolean    只显示 stale-queued (卡 >24h) 行
  Emits:
    - select(task) 点击任务行
    - update:showStaleOnly(v) 过滤 checkbox 同步
-->
<template>
  <div class="bf-table-wrap" data-el="batch-tasks-table-wrap">
    <div class="bf-toolbar">
      <el-checkbox
        v-if="staleCount > 0"
        v-model="showStaleOnlyLocal"
        size="small"
        data-el="bt-show-stale-only"
      >
        只看超时任务
        <span class="bf-stale-count">({{ staleCount }})</span>
      </el-checkbox>
    </div>
    <el-table
      :data="filteredTasks"
      size="small"
      border
      stripe
      highlight-current-row
      :row-key="(row) => row.id"
      :current-row-key="selectedId"
      :row-class-name="rowClassName"
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

      <el-table-column label="状态" width="160">
        <template #default="{ row }">
          <!-- running 时显示进度环 (bar/total) + phase 标签 -->
          <template v-if="row.status === 'running' && row._progress && row._progress.total_bars">
            <el-tooltip :show-after="500" placement="top">
              <template #content>
                <div>{{ _phaseLabel(row._progress.phase) }} ·
                  {{ row._progress.bar_idx }}/{{ row._progress.total_bars }}</div>
                <div v-if="row._progress.msg">{{ row._progress.msg }}</div>
              </template>
              <el-progress
                type="circle"
                :percentage="_progressPct(row._progress)"
                :stroke-width="6"
                :width="44"
                :status="row._progress.phase === 'failed' ? 'exception' : ''"
              />
            </el-tooltip>
            <span class="bf-progress-label">{{ row._progress.bar_idx }}/{{ row._progress.total_bars }}</span>
          </template>
          <template v-else>
            <el-tag size="small" :type="_statusType(row.status)">{{ _statusLabel(row.status) }}</el-tag>
            <!-- stale-queued 标记 (卡 queued > 24h 且从未调度) -->
            <el-tooltip v-if="isStaleQueued(row)" :show-after="500" placement="top">
              <template #content>
                卡 {{ _ageHours(row) }} 小时, 建议重测或联系 admin
              </template>
              <el-tag
                size="small"
                type="warning"
                effect="dark"
                class="bf-stale-tag"
                data-el="bt-stale-tag"
              >已超时</el-tag>
            </el-tooltip>
          </template>
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
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  schema: { type: Array, default: () => [] },
  selectedId: { type: Number, default: null },
  showStaleOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'update:showStaleOnly'])

// 本地镜像 showStaleOnly prop, 双向同步
const showStaleOnlyLocal = ref(props.showStaleOnly)
watch(() => props.showStaleOnly, (v) => { showStaleOnlyLocal.value = v })
watch(showStaleOnlyLocal, (v) => { emit('update:showStaleOnly', v) })

// ─────────────── Stale queued 判定 (change 2026-08-29-stale-queued-marker) ───────────────
//
// 满足全部条件才算 stale:
//   1. status === 'queued'
//   2. started_at 为空 (从未被 strategy_exec 调度过)
//   3. progress 为空 或 progress.phase === 'queued'
//   4. (now - created_at) >= 24h
//
// 数据源: listBatchTasks 返回的 dict 含 started_at / created_at / progress / status
// 纯前端计算, 无后端改动; 用户硬规则 2026-08-27: 不动 MySQL 任何数据
const STALE_THRESHOLD_MS = 24 * 3600 * 1000  // 24 hours

function isStaleQueued(row) {
  if (!row) return false
  if (row.status !== 'queued') return false
  if (row.started_at) return false
  if (row.progress && row.progress.phase && row.progress.phase !== 'queued') return false
  const created = row.created_at ? Date.parse(row.created_at) : NaN
  if (!Number.isFinite(created)) return false
  return (Date.now() - created) >= STALE_THRESHOLD_MS
}

function _ageHours(row) {
  const created = row.created_at ? Date.parse(row.created_at) : NaN
  if (!Number.isFinite(created)) return 0
  return Math.floor((Date.now() - created) / 3600000)
}

// stale 行数 (顶部 banner 用)
const staleCount = computed(() => props.tasks.filter(isStaleQueued).length)

// 过滤后表格
const filteredTasks = computed(() => {
  return showStaleOnlyLocal.value ? props.tasks.filter(isStaleQueued) : props.tasks
})

// el-table 行 class (stale 行加 .bf-row-stale)
function rowClassName({ row }) {
  return isStaleQueued(row) ? 'bf-row-stale' : ''
}

// ─────────────── 参数列 / 状态映射 ───────────────

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

// progress.phase 中文映射
const PHASE_LABELS = {
  start: '启动',
  load_script: '加载脚本',
  build_cerebro: '构造引擎',
  running: '回测中',
  live_running: '实盘运行',
  writing_result: '写结果',
  done: '完成',
  failed: '失败',
}
function _phaseLabel(phase) {
  return PHASE_LABELS[phase] || phase || '—'
}
function _progressPct(p) {
  if (!p || !p.total_bars || p.bar_idx == null) return 0
  return Math.min(100, Math.max(0, Math.round((Number(p.bar_idx) / Number(p.total_bars)) * 100)))
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
.bf-progress-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-left: 4px;
  vertical-align: middle;
  font-family: var(--font-mono, monospace);
}
.bf-table-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bf-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 24px;
}
.bf-stale-count {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: 4px;
}
.bf-stale-tag {
  margin-left: 4px;
}
/* stale 行灰色背景 + 降透明度 (与新任务区分) */
:deep(.bf-row-stale) {
  background: var(--bg-secondary, #f7f8fa) !important;
  opacity: 0.78;
}
:deep(.bf-row-stale td) {
  color: var(--text-secondary);
}
</style>