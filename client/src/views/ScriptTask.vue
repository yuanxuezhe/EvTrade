<!--
  ScriptTask.vue — 策略交易页 (v123 三层模型: script → strategy → strategy_task)

  两段式 UI:
    1. 顶部: 策略选择 / 新建 (仅 {name, script_id}, 不再填 params)
    2. 批次列表 (batch_no/时间/mode/task_count/best) → 批次内任务表格 (动态参数列)
       → 点击任务行下方下钻详情 (BacktestForm / BatchTasksTable / TaskDetail 子组件)

  实盘门禁: best_params 为空 → 提示"请先回测生成最优参数"并阻止; 有最优参数显示"实盘就绪"徽章。
  ws: 订阅 task_progress_update 实时刷新当前批次任务进度/状态。
-->
<template>
  <div class="script-task-view fade-in-up" data-el="script-task-view">
    <header class="st-header">
      <h3 class="st-title">策略交易</h3>
      <div class="st-actions">
        <el-select
          v-model="strategyId"
          placeholder="选择策略"
          filterable
          :loading="strategiesLoading"
          style="width: 260px"
          data-el="st-strategy-select"
          @change="onStrategyChange"
        >
          <el-option
            v-for="s in strategies"
            :key="s.strategy_id"
            :value="s.strategy_id"
            :label="s.name"
          >
            <span>{{ s.name }}</span>
            <span class="st-opt-meta">#{{ s.strategy_id }} · {{ scriptNameById(s.script_id) }}</span>
            <el-tag v-if="hasBestParams(s)" size="small" type="danger" effect="dark">实盘</el-tag>
          </el-option>
        </el-select>
        <el-button :icon="Plus" type="primary" @click="openCreate" data-el="st-create">新建策略</el-button>
        <el-button :icon="Refresh" @click="reloadAll" data-el="st-refresh">刷新</el-button>
      </div>
    </header>

    <!-- 策略工具栏: 回测 / 实盘 + 实盘徽章 -->
    <div v-if="strategyDetail" class="st-strategy-bar">
      <div class="st-strategy-info">
        <span class="st-strategy-name">{{ strategyDetail.name }}</span>
        <el-tag size="small" effect="plain">{{ strategyDetail.status }}</el-tag>
        <el-tag v-if="liveReady" size="small" type="danger" effect="dark" data-el="st-live-badge">实盘就绪</el-tag>
        <span v-else class="st-live-hint">未回测 · 无最优参数</span>
        <span v-if="bestParamsText" class="st-best-params" :title="bestParamsText">最佳参数: {{ bestParamsText }}</span>
      </div>
      <div class="st-strategy-actions">
        <el-button type="primary" @click="openBacktest" data-el="st-backtest">回测</el-button>
        <el-button type="danger" :disabled="!liveReady" @click="onLive" data-el="st-live">实盘</el-button>
      </div>
    </div>

    <!-- 批次列表 -->
    <el-card shadow="never" class="st-card" data-el="st-batches-card">
      <template #header>
        <div class="st-card-head">
          <span>批次列表</span>
          <span v-if="strategyId" class="st-card-sub">{{ batches.length }} 个批次</span>
        </div>
      </template>
      <el-table
        v-loading="batchesLoading"
        :data="batches"
        size="small"
        border
        stripe
        highlight-current-row
        :row-key="(b) => b.batch_no ?? b.created_at"
        :current-row-key="selectedBatchNo"
        empty-text="暂无批次, 点击「回测」创建"
        data-el="st-batches-table"
        @row-click="onBatchClick"
      >
        <el-table-column label="批号" prop="batch_no" width="80" />
        <el-table-column label="创建时间" prop="created_at" width="170" />
        <el-table-column label="模式" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.mode === 'live' ? 'danger' : 'info'">
              {{ row.mode === 'live' ? '实盘' : '回测' }}
            </el-tag>
            <el-tag v-if="row.abandoned" size="small" type="info" effect="dark">已废弃</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="任务" width="120">
          <template #default="{ row }">
            <template v-if="row.abandoned">
              <span class="st-muted">{{ row.abandoned_count }}/{{ row.task_count }} 已废弃</span>
            </template>
            <template v-else>
              <span>{{ row.finished_count }}/{{ row.task_count }} 完成</span>
              <el-tag v-if="row.failed_count" size="small" type="danger">{{ row.failed_count }} 失败</el-tag>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="最优指标" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.best_metric_value !== null && row.best_metric_value !== undefined" class="up">
              {{ Number(row.best_metric_value).toFixed(4) }}
            </span>
            <span v-else class="st-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="最优参数" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <code v-if="row.best_params" class="st-best-code">{{ JSON.stringify(row.best_params) }}</code>
            <span v-else class="st-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              link
              type="primary"
              :disabled="!_canRetest(row)"
              @click.stop="onRetest(row)"
              data-el="st-retest"
            >重测</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 批次内任务 -->
    <el-card v-if="selectedBatchNo != null" shadow="never" class="st-card" data-el="st-batch-tasks-card">
      <template #header>
        <div class="st-card-head">
          <span>批次 #{{ selectedBatchNo }} 任务</span>
          <span class="st-card-sub">{{ batchTasks.length }} 个任务</span>
          <el-button
            v-if="selectedTaskRunning"
            size="small"
            type="danger"
            @click="onStopTask"
            data-el="st-stop"
          >停止运行</el-button>
        </div>
      </template>
      <BatchTasksTable
        :tasks="batchTasks"
        :schema="schema"
        :selected-id="selectedTaskId"
        @select="onTaskSelect"
      />
    </el-card>

    <!-- 任务详情下钻 -->
    <el-card v-if="detail" shadow="never" class="st-card" data-el="st-detail-card">
      <TaskDetail :task="detail" :strategy-name="strategyDetail?.name || ''" />
    </el-card>
    <el-empty v-else-if="selectedTaskId != null" description="加载任务详情..." />

    <!-- 新建策略 dialog -->
    <el-dialog v-model="createOpen" title="新建策略" width="460px" data-el="st-create-dialog">
      <el-form label-width="90px" size="small">
        <el-form-item label="策略名称">
          <el-input v-model="createForm.name" placeholder="如 双均线" data-el="st-create-name" />
        </el-form-item>
        <el-form-item label="脚本">
          <el-select
            v-model="createForm.script_id"
            style="width: 100%"
            filterable
            placeholder="选择脚本"
            data-el="st-create-script"
          >
            <el-option v-for="s in scripts" :key="s.id" :value="s.id" :label="s.name">
              <span>{{ s.name }}</span>
              <span class="st-opt-meta">{{ s.id }}</span>
            </el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreateStrategy">创建</el-button>
      </template>
    </el-dialog>

    <!-- 回测抽屉 (BacktestForm) -->
    <BacktestForm :visible="backtestVisible" :schema="schema" @update:visible="(v) => (backtestVisible = v)" @submit="onBacktestSubmit" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { scriptStrategyApi } from '../api/script_strategy'
import { useWsStore } from '../stores/ws'
import BacktestForm from '../components/strategy/BacktestForm.vue'
import BatchTasksTable from '../components/strategy/BatchTasksTable.vue'
import TaskDetail from '../components/strategy/TaskDetail.vue'

// ─────────────── 状态 ───────────────
const strategies = ref([])
const strategiesLoading = ref(false)
const strategyId = ref(null)
const strategyDetail = ref(null)   // getStrategy → { ..., script: { params_schema } }
const scripts = ref([])            // 脚本库 (新建策略用)
const batches = ref([])
const batchesLoading = ref(false)
const selectedBatchNo = ref(null)
const batchTasks = ref([])
const selectedTaskId = ref(null)
const detail = ref(null)
const createOpen = ref(false)
const creating = ref(false)
const backtestVisible = ref(false)
const createForm = ref({ name: '', script_id: null })

const wsStore = useWsStore()

// ─────────────── computeds ───────────────
const schema = computed(() => strategyDetail.value?.script?.params_schema || [])
const liveReady = computed(() => hasBestParams(strategyDetail.value))
const bestParamsText = computed(() => {
  const bp = strategyDetail.value?.best_params
  if (!bp) return ''
  return Object.entries(bp).map(([k, v]) => `${k}=${v}`).join(', ')
})
const selectedTaskRunning = computed(() => detail.value?.status === 'running')

function hasBestParams(s) {
  return !!(s?.best_params && Object.keys(s.best_params).length)
}
function scriptNameById(id) {
  const s = scripts.value.find((x) => x.id === id)
  return s?.name || id
}
function _errMsg(e, fallback = '未知错误') {
  const d = e?.response?.data?.detail
  return (typeof d === 'string' ? d : d?.msg) || e?.message || fallback
}

// ─────────────── 加载 ───────────────
async function loadStrategies() {
  strategiesLoading.value = true
  try {
    strategies.value = (await scriptStrategyApi.listStrategies()) || []
    if (!strategies.value.length) {
      strategyId.value = null
      strategyDetail.value = null
    } else if (!strategies.value.some((s) => s.strategy_id === strategyId.value)) {
      strategyId.value = strategies.value[0].strategy_id
    }
  } catch (e) {
    ElMessage.error('加载策略失败: ' + _errMsg(e))
  } finally {
    strategiesLoading.value = false
  }
}

async function loadStrategyDetail() {
  if (strategyId.value == null) return
  try {
    strategyDetail.value = await scriptStrategyApi.getStrategy(strategyId.value)
  } catch (e) {
    ElMessage.error('加载策略详情失败: ' + _errMsg(e))
  }
}

async function loadBatches() {
  if (strategyId.value == null) return
  batchesLoading.value = true
  try {
    batches.value = (await scriptStrategyApi.listBatches(strategyId.value)) || []
  } catch (e) {
    ElMessage.error('加载批次失败: ' + _errMsg(e))
  } finally {
    batchesLoading.value = false
  }
}

async function loadBatchTasks() {
  if (strategyId.value == null || selectedBatchNo.value == null) return
  try {
    batchTasks.value = (await scriptStrategyApi.listBatchTasks(strategyId.value, selectedBatchNo.value)) || []
  } catch (e) {
    ElMessage.error('加载批次任务失败: ' + _errMsg(e))
  }
}

async function loadDetail() {
  if (selectedTaskId.value == null) return
  try {
    detail.value = await scriptStrategyApi.getTask(selectedTaskId.value)
  } catch (e) {
    ElMessage.error('加载任务详情失败: ' + _errMsg(e))
  }
}

async function reloadAll() {
  await loadStrategies()
  if (strategyId.value != null) {
    await loadStrategyDetail()
    await loadBatches()
  }
}

// ─────────────── 交互 ───────────────
async function onStrategyChange() {
  selectedBatchNo.value = null
  selectedTaskId.value = null
  detail.value = null
  batchTasks.value = []
  if (strategyId.value == null) return
  await loadStrategyDetail()
  await loadBatches()
}

async function onBatchClick(batch) {
  if (batch.batch_no === selectedBatchNo.value) return
  selectedBatchNo.value = batch.batch_no
  selectedTaskId.value = null
  detail.value = null
  await loadBatchTasks()
}

async function onTaskSelect(task) {
  selectedTaskId.value = task.id
  await loadDetail()
}

function openBacktest() {
  if (strategyId.value == null) {
    ElMessage.warning('请先选择策略')
    return
  }
  if (!schema.value.length) {
    ElMessage.warning('该脚本无参数 schema, 无法配置回测')
    return
  }
  backtestVisible.value = true
}

async function onBacktestSubmit(payload) {
  try {
    const res = await scriptStrategyApi.backtestStrategy(strategyId.value, payload)
    ElMessage.success(res.mode === 'sweep' ? `扫描已提交, ${res.total_runs} 个组合` : '回测已提交')
    backtestVisible.value = false
    await reloadAll()
    if (res.batch_no != null) {
      selectedBatchNo.value = res.batch_no
      await loadBatchTasks()
    }
  } catch (e) {
    ElMessage.error('提交失败: ' + _errMsg(e))
  }
}

async function onLive() {
  if (!liveReady.value) {
    ElMessage.warning('请先回测生成最优参数')
    return
  }
  const { value: stock } = await ElMessageBox.prompt('输入实盘标的代码', '启动实盘', {
    inputPlaceholder: '如 600519.SH',
    confirmButtonText: '启动',
    cancelButtonText: '取消',
  }).catch(() => ({}))
  if (!stock) return
  try {
    const res = await scriptStrategyApi.startLive(strategyId.value, { stock_code: stock.trim() })
    ElMessage.success(`实盘已启动, batch #${res.batch_no}`)
    await reloadAll()
    if (res.batch_no != null) {
      selectedBatchNo.value = res.batch_no
      await loadBatchTasks()
    }
    if (res.task_id != null) {
      selectedTaskId.value = res.task_id
      await loadDetail()
    }
  } catch (e) {
    ElMessage.error('实盘启动失败: ' + _errMsg(e))
  }
}

async function onStopTask() {
  if (!detail.value?.id) return
  try {
    await scriptStrategyApi.stopTask(detail.value.id)
    ElMessage.success('已发送停止指令')
    await loadDetail()
  } catch (e) {
    ElMessage.error('停止失败: ' + _errMsg(e))
  }
}

// v124 重测: 仅回测批次 (非 live), 且批次无运行中/排队 task
function _canRetest(batch) {
  if (!batch || batch.mode === 'live') return false
  const running = (batch.task_count || 0) - (batch.finished_count || 0)
    - (batch.failed_count || 0) - (batch.abandoned_count || 0)
  return running <= 0
}

async function onRetest(batch) {
  const { value } = await ElMessageBox.confirm(
    `按原配置重测批次 #${batch.batch_no}？将生成新批次重新执行, 原批次任务将废弃。`,
    '重测批次',
    { confirmButtonText: '重测', cancelButtonText: '取消', type: 'warning' },
  ).catch(() => ({}))
  if (!value) return
  try {
    const res = await scriptStrategyApi.retestBatch(strategyId.value, batch.batch_no)
    ElMessage.success(`重测已提交, 新批次 #${res.batch_no} (${res.total_runs} 个任务)`)
    await reloadAll()
    if (res.batch_no != null) {
      selectedBatchNo.value = res.batch_no
      await loadBatchTasks()
    }
  } catch (e) {
    ElMessage.error('重测失败: ' + _errMsg(e))
  }
}

function openCreate() {
  createForm.value = { name: '', script_id: null }
  createOpen.value = true
}

async function onCreateStrategy() {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请填写策略名称')
    return
  }
  if (!createForm.value.script_id) {
    ElMessage.warning('请选择脚本')
    return
  }
  creating.value = true
  try {
    const s = await scriptStrategyApi.createStrategy({
      name: createForm.value.name.trim(),
      script_id: createForm.value.script_id,
    })
    ElMessage.success(`已创建策略 #${s.strategy_id}`)
    createOpen.value = false
    await reloadAll()
    strategyId.value = s.strategy_id
    await loadStrategyDetail()
    await loadBatches()
  } catch (e) {
    ElMessage.error('创建失败: ' + _errMsg(e))
  } finally {
    creating.value = false
  }
}

// ─────────────── ws 实时刷新 (task_progress_update) ───────────────
let _wsBatchTimer = null
let _wsTaskTimer = null
function _scheduleReloadBatches() {
  if (_wsBatchTimer) return
  _wsBatchTimer = setTimeout(() => {
    _wsBatchTimer = null
    loadBatches()
  }, 800)
}
function _scheduleReloadTasks() {
  if (_wsTaskTimer) return
  _wsTaskTimer = setTimeout(() => {
    _wsTaskTimer = null
    loadBatchTasks()
  }, 800)
}

onMounted(async () => {
  await loadStrategies()
  if (strategyId.value != null) {
    await loadStrategyDetail()
    await loadBatches()
  }
  try {
    scripts.value = (await scriptStrategyApi.listScripts()) || []
  } catch (e) { /* 脚本库加载失败不阻塞主流程 */ }
})

// 订阅 ws 进度: 属于当前批次 → 节流刷新任务表格 + 就地更新详情进度/状态
watch(() => wsStore.lastTaskProgress, (msg) => {
  if (!msg || strategyId.value == null) return
  _scheduleReloadBatches()
  if (msg.task_id == null) return
  const inBatch = batchTasks.value.some((t) => t.id === msg.task_id)
  if (!inBatch) return
  _scheduleReloadTasks()
  if (msg.task_id === selectedTaskId.value && detail.value && (msg.status || msg.progress)) {
    detail.value = {
      ...detail.value,
      status: msg.status || detail.value.status,
      progress: msg.progress || detail.value.progress,
    }
  }
  if (msg.status === 'finished' || msg.status === 'failed' || msg.status === 'stopped') {
    if (msg.task_id === selectedTaskId.value) loadDetail()
  }
})

onBeforeUnmount(() => {
  if (_wsBatchTimer) clearTimeout(_wsBatchTimer)
  if (_wsTaskTimer) clearTimeout(_wsTaskTimer)
})
</script>

<style scoped>
.script-task-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 12px;
  overflow-y: auto;
}
.st-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.st-title { margin: 0; font-size: 16px; font-weight: 600; }
.st-actions { display: flex; align-items: center; gap: 8px; }
.st-opt-meta { color: var(--text-placeholder); font-size: 12px; margin: 0 6px; }

.st-strategy-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: var(--bg-secondary, #f7f8fa);
  border: 1px solid var(--border-light, #ebeef5);
  border-radius: 6px;
  flex-shrink: 0;
}
.st-strategy-info { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 13px; }
.st-strategy-name { font-size: 14px; font-weight: 600; }
.st-live-hint { color: var(--text-placeholder); font-size: 12px; }
.st-best-params { color: var(--text-secondary); font-size: 12px; }
.st-strategy-actions { display: flex; gap: 8px; }

.st-card { flex-shrink: 0; }
.st-card-head { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
.st-card-sub { font-size: 12px; font-weight: 400; color: var(--text-secondary); margin-right: auto; }
.st-best-code { font-family: var(--font-mono, monospace); font-size: 12px; }
.st-muted { color: var(--text-placeholder); }
.up { color: var(--color-up, #f56c6c); font-weight: 600; }
</style>
