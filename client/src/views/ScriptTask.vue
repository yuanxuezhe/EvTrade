<!--
  ScriptTask.vue — 策略交易页 (三层模型: script → strategy → strategy_task)

  两段式 UI:
    1. 顶部: 策略选择 / 新建 ({name, script_id, stock_code}, 标的必选)
    2. 批次列表 (batch_no/时间/mode/task_count/best) → 批次内任务表格 (动态参数列)
       → 点击任务行下方下钻详情 (BacktestForm / BatchTasksTable / TaskDetail 子组件)

  策略模块纯回测 (无实盘)。他人公开策略只读精简 (无回测/批次入口), 公开/私有开关仅 owner。
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
            <el-tag v-if="s.is_public" size="small" type="success" effect="plain">公开</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">私有</el-tag>
            <el-tag v-if="s.user_id !== currentUserId" size="small" type="warning" effect="plain">
              u/{{ s.user_id }}
            </el-tag>
          </el-option>
        </el-select>
        <el-button :icon="Plus" type="primary" @click="openCreate" data-el="st-create">新建策略</el-button>
        <el-button :icon="Refresh" @click="reloadAll" data-el="st-refresh">刷新</el-button>
      </div>
    </header>

    <!-- 策略工具栏: 标的 / 公开开关 (仅 owner) -->
    <div v-if="strategyDetail" class="st-strategy-bar">
      <div class="st-strategy-info">
        <span class="st-strategy-name">{{ strategyDetail.name }}</span>
        <el-tag size="small" effect="plain">{{ strategyDetail.status }}</el-tag>
        <el-tag size="small" type="info" effect="plain">标的 {{ strategyDetail.stock_code || '未绑定' }}</el-tag>
        <el-tag v-if="!isOwner" size="small" type="warning" effect="dark">他人公开策略 · 只读</el-tag>
        <el-tag v-else :type="strategyDetail.is_public ? 'success' : 'info'" effect="dark" data-el="st-public-tag">
          {{ strategyDetail.is_public ? '公开' : '私有' }}
        </el-tag>
        <span v-if="isOwner && bestParamsText" class="st-best-params" :title="bestParamsText">最佳参数: {{ bestParamsText }}</span>
      </div>
      <div class="st-strategy-actions">
        <el-button v-if="isOwner" type="primary" @click="openBacktest" data-el="st-backtest">回测</el-button>
        <el-switch
          v-if="isOwner"
          v-model="strategyDetail.is_public"
          active-text="公开"
          inactive-text="私有"
          @change="onTogglePublic"
          data-el="st-public-switch"
        />
      </div>
    </div>

    <!-- 批次列表 (仅 owner) -->
    <el-card v-if="isOwner" shadow="never" class="st-card" data-el="st-batches-card">
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
            <el-tag size="small" type="info">回测</el-tag>
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
    <el-empty v-else-if="strategyDetail && !isOwner" description="他人公开策略只读: 不可查看批次/详情/回测" />

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
        :tasks="batchTasksWithProgress"
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
        <el-form-item label="绑定标的" required>
          <el-input v-model="createForm.stock_code" placeholder="如 600519.SH" data-el="st-create-stock" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreateStrategy">创建</el-button>
      </template>
    </el-dialog>

    <!-- 回测抽屉 (BacktestForm) -->
    <BacktestForm :visible="backtestVisible" :schema="schema" :stock-code="strategyDetail?.stock_code || ''" @update:visible="(v) => (backtestVisible = v)" @submit="onBacktestSubmit" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { scriptStrategyApi } from '../api/script_strategy'
import { useWsStore } from '../stores/ws'
import { useAuthStore } from '../stores/auth'
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
const createForm = ref({ name: '', script_id: null, stock_code: '' })
const currentUserId = ref(null)   // auth store user.id (owner 判断)

const wsStore = useWsStore()

// ─────────────── computeds ───────────────
const schema = computed(() => strategyDetail.value?.script?.params_schema || [])
const isOwner = computed(() =>
  strategyDetail.value != null && strategyDetail.value.user_id === currentUserId.value
)
const bestParamsText = computed(() => {
  const bp = strategyDetail.value?.best_params
  if (!bp) return ''
  return Object.entries(bp).map(([k, v]) => `${k}=${v}`).join(', ')
})
const selectedTaskRunning = computed(() => detail.value?.status === 'running')

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
  if (strategyId.value == null || !isOwner.value) return
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

async function onTogglePublic(val) {
  if (strategyId.value == null || val == null) return
  const sid = strategyId.value
  try {
    const d = await scriptStrategyApi.updateStrategy(sid, { is_public: val })
    if (strategyId.value !== sid) return  // 过期响应 (期间切了策略) 丢弃
    // update_strategy 响应不含 script → 保留现有 script, 否则 schema 清空, 回测被挡
    strategyDetail.value = { ...d, script: strategyDetail.value?.script }
    ElMessage.success(val ? '策略已设为公开' : '策略已设为私有')
    await loadStrategies()  // 刷新列表里的公开/私有标记
  } catch (e) {
    if (strategyId.value !== sid) return
    strategyDetail.value = { ...strategyDetail.value, is_public: !val }  // 回滚
    ElMessage.error('切换失败: ' + _errMsg(e))
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

// 重测: 批次无运行中/排队 task
function _canRetest(batch) {
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
  createForm.value = { name: '', script_id: null, stock_code: '' }
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
  if (!createForm.value.stock_code.trim()) {
    ElMessage.warning('请填写策略绑定标的')
    return
  }
  creating.value = true
  try {
    const s = await scriptStrategyApi.createStrategy({
      name: createForm.value.name.trim(),
      script_id: createForm.value.script_id,
      stock_code: createForm.value.stock_code.trim(),
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

// ─────────────── 轮询 fallback (queued/running 时启, 全部完成停) ───────────────
let _pollTimer = null
const POLL_INTERVAL_MS = 3000

const _hasActiveTask = computed(() => {
  return batchTasks.value.some((t) => t.status === 'queued' || t.status === 'running')
})

function _startPolling() {
  if (_pollTimer) return
  _pollTimer = setInterval(() => {
    // 只在还有活跃 task 时拉 (watch _hasActiveTask 控制启停)
    if (_hasActiveTask.value) {
      loadBatches()
      loadBatchTasks()
    }
  }, POLL_INTERVAL_MS)
}
function _stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer)
    _pollTimer = null
  }
}

// ─────────────── ws 实时刷新 (task_progress_update) ───────────────
// 进度暂存: task_id → 最新 progress (用于表格行 _progress 字段, 不依赖 reload)
const taskProgressMap = ref(new Map())
let _wsBatchTimer = null
let _wsTaskTimer = null

// 把 batchTasks 跟 taskProgressMap 合并, 给 BatchTasksTable 用 (row._progress)
const batchTasksWithProgress = computed(() => {
  const m = taskProgressMap.value
  return batchTasks.value.map((t) => {
    const p = m.get(t.id)
    return p ? { ...t, _progress: p } : t
  })
})

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

// 启动/停轮询 (watch 当前 batch 的活跃 task 数)
watch(_hasActiveTask, (has) => {
  if (has) _startPolling()
  else _stopPolling()
}, { immediate: true })

onMounted(async () => {
  currentUserId.value = Number(useAuthStore().user?.id) || null
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
  // 暂存 progress → 表格行立即显示进度环 (无需等 reload)
  if (msg.progress) {
    // Map 不可直接 reactive.set 触发 watch; 用 new Map + 整体替换
    const m = new Map(taskProgressMap.value)
    m.set(msg.task_id, msg.progress)
    taskProgressMap.value = m
  }
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
  _stopPolling()
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
.st-best-params { color: var(--text-secondary); font-size: 12px; }
.st-strategy-actions { display: flex; gap: 8px; }

.st-card { flex-shrink: 0; }
.st-card-head { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
.st-card-sub { font-size: 12px; font-weight: 400; color: var(--text-secondary); margin-right: auto; }
.st-best-code { font-family: var(--font-mono, monospace); font-size: 12px; }
.st-muted { color: var(--text-placeholder); }
.up { color: var(--color-up, #f56c6c); font-weight: 600; }
</style>
