<!--
  T0Trade.vue — 快速做T 主页面 (v55 切到 task 视角)

  架构变更：
    v54 前: 主表 holdings 视角 (每行 = 1 持仓标的) + drawer T0TaskList + dialog T0TaskCreateDialog
    v55:   主表 task 视角 (每行 = 1 做T 任务) + 删 drawer T0TaskList + "添加任务" 按钮 → dialog (左 HoldingsPanel + 右 T0TaskCreateDialog)

  数据源: t0TasksStore.tasks (一 task 一行)
  持仓:   useHoldingsStore().positions (供 HoldingsPanel 嵌入 dialog 用)
  行情:   useQuoteStore()

  v55 主表 8 列:
    1. 状态 (el-tag)
    2. 任务编号 (#${task.id})
    3. 标的 (代码 + 名称)
    4. 底仓+目标 (= base_volume + target_volume)
    5. 当前持仓 (task.summary.position_vol)
    6. 做T盈亏 (task.summary.realized_pnl, 红涨绿跌)
    7. 做T收益率% (calcT0ReturnRate)
    8. 操作 (详情 / 配平 / 平仓)

  v55 "添加任务" dialog (900px wide):
    ┌──────────────────┬──────────────────────────┐
    │ HoldingsPanel    │ T0TaskCreateDialog        │
    │ (左 350px)       │ (右 520px)                │
    │ - 单击 → select-stock → 回填 stock_code │
    └──────────────────┴──────────────────────────┘
-->
<template>
  <div class="t0-trade fade-in-up">
    <!-- Header: 标题 + 仓位% + 价格档 + 任务快速选择 + 添加任务按钮 + 刷新 -->
    <div class="t0-header">
      <span class="t0-title">⚡ 快速做T</span>
      <div class="qs-row">
        <el-tooltip content="选择/取消当前做T归属的 task；新建请用添加任务入口" placement="top">
          <el-select
            v-model="selectedTaskId"
            placeholder="选 task"
            size="small"
            clearable
            filterable
            class="qs-task-select"
            style="width: 200px"
            @change="onTaskChange"
          >
            <el-option
              v-for="t in filteredActiveTasks"
              :key="t.id"
              :value="t.id"
              :label="`#${t.id} ${t.stock_code}`"
            />
          </el-select>
        </el-tooltip>
        <el-button type="primary" size="small" :icon="Plus" @click="onAddTaskOpen">添加任务</el-button>
        <el-button size="small" @click="onRefresh" :loading="refreshing">刷新</el-button>
      </div>
    </div>

    <!-- 主表 8 列 (v55 task 视角) -->
    <el-table
      :data="taskRows"
      :row-class-name="ptRowClass"
      @sort-change="onSortChange"
      class="task-table"
      empty-text="暂无 T0 任务，点击「添加任务」按钮创建"
      size="default"
    >
      <!-- 1. 状态 (100) -->
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>

      <!-- 2. 任务编号 (90) -->
      <el-table-column prop="id" label="任务编号" width="90">
        <template #default="{ row }">
          <span class="text-mono">#{{ row.id }}</span>
        </template>
      </el-table-column>

      <!-- 3. 标的 (180: 代码 100 + 名称 80) -->
      <el-table-column label="标的" min-width="180">
        <template #default="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
          <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
        </template>
      </el-table-column>

      <!-- 4. 底仓+目标 (140, sortable) -->
      <el-table-column prop="balance_target" label="底仓+目标" align="right" width="140" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono">
            {{ formatNumber(row.base_volume || 0) }} + {{ formatNumber(row.target_volume || 0) }}
            = <b>{{ formatNumber((row.base_volume || 0) + (row.target_volume || 0)) }}</b>
          </span>
        </template>
      </el-table-column>

      <!-- 5. 当前持仓 (100, sortable) -->
      <el-table-column prop="position_vol" label="当前持仓" align="right" width="100" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono">{{ formatNumber(row.summary?.position_vol ?? 0) }}</span>
        </template>
      </el-table-column>

      <!-- 6. 做T盈亏 (110, sortable) -->
      <el-table-column prop="t0_pnl" label="做T盈亏" align="right" width="110" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono" :class="(row.summary?.realized_pnl ?? 0) >= 0 ? 'up' : 'down'">
            {{ (row.summary?.realized_pnl ?? 0) >= 0 ? '+' : '' }}{{ formatAmount(row.summary?.realized_pnl ?? 0) }}
          </span>
        </template>
      </el-table-column>

      <!-- 7. 做T收益率% (120, sortable) -->
      <el-table-column prop="t0_return_rate" label="做T收益率%" align="right" width="120" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono" :class="t0ReturnRateForRow(row) >= 0 ? 'up' : 'down'">
            {{ (t0ReturnRateForRow(row) * 100).toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- 8. 操作 (240 fixed right) — 详情 / 配平 / 平仓 -->
      <el-table-column label="操作" align="center" width="240" fixed="right">
        <template #default="{ row }">
          <div class="op-col">
            <el-button type="primary" link size="small" @click="onOpenTaskDetail(row.id)">详情</el-button>
            <el-button
              v-if="row.status === 'active'"
              type="warning"
              link
              size="small"
              @click="onBalanceTask(row.id)"
            >配平</el-button>
            <el-button
              v-if="row.status === 'active'"
              type="danger"
              link
              size="small"
              @click="onCloseTask(row.id)"
            >平仓</el-button>
            <el-button
              v-if="row.status !== 'archived'"
              type="info"
              link
              size="small"
              @click="onArchiveTask(row.id)"
            >归档</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加任务 dialog (900px, 左 HoldingsPanel + 右 T0TaskCreateDialog) -->
    <el-dialog
      v-model="createDialogVisible"
      title="添加做T任务"
      width="900px"
      :close-on-click-modal="false"
      align-center
      @open="onAddTaskDialogOpen"
    >
      <div class="add-task-grid">
        <!-- 左侧: 持仓面板 (HoldingsPanel) -->
        <div class="add-task-left">
          <div class="left-hint">
            <el-icon><InfoFilled /></el-icon>
            <span>单击持仓行自动填充右侧股票代码</span>
          </div>
          <HoldingsPanel @select-stock="onHoldingSelected" />
        </div>

        <!-- 右侧: 创建任务表单 -->
        <div class="add-task-right">
          <T0TaskCreateDialog
            v-if="createDialogVisible"
            inline
            :visible="createDialogVisible"
            :loading="createDialogLoading"
            :default-stock-code="stockCode || ''"
            :external-stock-code="externalStockCode"
            @submit="onCreateTaskSubmit"
            @cancel="createDialogVisible = false"
          />
        </div>
      </div>
    </el-dialog>

    <!-- task 详情 drawer (保留 v54) -->
    <el-drawer v-model="tasksDetailVisible" :title="`task #${viewingTaskId} 详情`" size="55%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskDetail v-if="tasksDetailVisible" :task-id="viewingTaskId" embedding="drawer" />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Plus, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { useT0TasksStore } from '../stores/t0_tasks'
import T0TaskDetail from '../components/trade/T0TaskDetail.vue'
import T0TaskCreateDialog from '../components/trade/T0TaskCreateDialog.vue'
import HoldingsPanel from '../components/trade/HoldingsPanel.vue'
import { formatNumber, formatAmount } from '../utils/format'
import { stockName } from '../utils/stockNames'
import { calcT0ReturnRate } from '../lib/t0-calc'
import { makeLogger } from '../utils/logger'

const log = makeLogger('T0Trade')

const holdingsStore = useHoldingsStore()
const quoteStore = useQuoteStore()
const t0TasksStore = useT0TasksStore()
const { positions } = storeToRefs(holdingsStore)

const stockCode = ref(null)
const refreshing = ref(false)

// task 管理
const selectedTaskId = ref(null)
const tasksDetailVisible = ref(false)
const viewingTaskId = ref(null)

// 添加任务 dialog
const createDialogVisible = ref(false)
const createDialogLoading = ref(false)
const externalStockCode = ref('')  // HoldingsPanel 选中 → 驱动 dialog 表单

const filteredActiveTasks = computed(() => {
  const all = t0TasksStore.activeTasks || []
  if (!stockCode.value) return all
  return all.filter((t) => t.stock_code === stockCode.value)
})

watch([stockCode, filteredActiveTasks], ([code, list]) => {
  if (selectedTaskId.value && !list.find((t) => t.id === selectedTaskId.value)) {
    selectedTaskId.value = null
  }
})

// ---- 主表数据源 (v55 task 视角) ----
const taskRows = computed(() => t0TasksStore.tasks || [])

function ptRowClass({ row }) {
  const classes = []
  if (row.id === selectedTaskId.value) classes.push('is-selected')
  return classes.join(' ')
}

// ---- 排序 (简化: 只支持 做T盈亏 / 做T收益率% / 当前持仓 3 列) ----
const sortBy = ref(null)
const sortOrder = ref(null)
function onSortChange({ prop, order }) {
  sortBy.value = order ? prop : null
  sortOrder.value = order || null
}
function _taskSortValue(row, key) {
  switch (key) {
    case 'position_vol': return Number(row.summary?.position_vol) || 0
    case 't0_pnl': return Number(row.summary?.realized_pnl) || 0
    case 't0_return_rate': return t0ReturnRateForRow(row)
    default: return 0
  }
}
const sortedTaskRows = computed(() => {
  const list = [...taskRows.value]
  if (!sortBy.value || !sortOrder.value) return list
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  list.sort((a, b) => (_taskSortValue(a, sortBy.value) - _taskSortValue(b, sortBy.value)) * dir)
  return list
})

// ---- 状态 helpers ----
function statusLabel(s) {
  return s === 'active' ? '活跃' : s === 'closed' ? '已平仓' : s === 'archived' ? '已归档' : s || '—'
}
function statusTagType(s) {
  if (s === 'active') return 'primary'
  if (s === 'closed') return 'info'
  return 'danger'
}

// ---- 收益率 (v54 复用 calcT0ReturnRate 纯函数) ----
function t0ReturnRateForRow(row) {
  // task 没有直接的 last_vol/cost_price, 用 base_volume 代替底仓 (近似);
  //   真实"持仓成本价" 留作 v56 task cost 字段扩展
  const baseVol = row.base_volume || 0
  return calcT0ReturnRate(
    { last_vol: baseVol, cost_price: 1 },  // 占位 cost_price=1, 实际意义 v56 调整
    { today_buy_amount: 0, today_sell_amount: row.summary?.realized_pnl || 0 },
  )
}

// ---- task 操作 ----
function onTaskChange(taskId) {
  selectedTaskId.value = taskId
  if (taskId) {
    const t = t0TasksStore.tasksById[taskId]
    if (t) stockCode.value = t.stock_code
  }
}
function onOpenTaskDetail(taskId) {
  viewingTaskId.value = taskId
  tasksDetailVisible.value = true
}
async function onBalanceTask(taskId) {
  try {
    const r = await t0TasksStore.balanceTask(taskId)
    const dir = r.action === 'BUY' ? '买入' : r.action === 'SELL' ? '卖出' : '无需操作'
    ElMessage.info(`task #${taskId} 配平建议：${dir} ${r.volume} 股 — ${r.reason}`)
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}
async function onCloseTask(taskId) {
  try {
    await ElMessageBox.confirm(
      `确认一键平仓 task #${taskId} 到 base_volume？将生成平仓委托`,
      '一键平仓', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  try {
    const r = await t0TasksStore.closeTask(taskId)
    ElMessage.success(`task #${taskId} 已平仓：${r.action} ${r.volume} 股`)
    await t0TasksStore.loadTasks()
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}
async function onArchiveTask(taskId) {
  try {
    await ElMessageBox.confirm(
      `确认归档 task #${taskId}?`,
      '归档 task', { confirmButtonText: '确认归档', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  try {
    await t0TasksStore.archiveTask(taskId)
    ElMessage.success(`task #${taskId} 已归档`)
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}

// ---- 添加任务 dialog ----
function onAddTaskOpen() {
  externalStockCode.value = ''
  createDialogVisible.value = true
}
function onAddTaskDialogOpen() {
  // dialog 打开后清空 externalStockCode, 让 HoldingsPanel 单击能驱动
  externalStockCode.value = ''
}
function onHoldingSelected({ stock_code, stock_name }) {
  externalStockCode.value = stock_code
  ElMessage.info(`已选中 ${stock_code} ${stock_name || ''}，请在右侧填写任务参数`)
}
async function onCreateTaskSubmit(form) {
  createDialogLoading.value = true
  try {
    const t = await t0TasksStore.createTask(form)
    if (t && t.id) {
      ElMessage.success(`task #${t.id} 创建成功，自动选中`)
      selectedTaskId.value = t.id
      if (t.stock_code) stockCode.value = t.stock_code
      createDialogVisible.value = false
    }
  } finally {
    createDialogLoading.value = false
  }
}

// ---- 刷新 ----
async function onRefresh() {
  refreshing.value = true
  try {
    await t0TasksStore.loadTasks()
  } finally {
    refreshing.value = false
  }
}

// ---- 初始化 ----
onMounted(async () => {
  await t0TasksStore.loadTasks()
  if (!stockCode.value && taskRows.value.length > 0) {
    stockCode.value = taskRows.value[0].stock_code
  }
})
</script>

<style scoped>
.t0-trade {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.t0-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.t0-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary, #303133);
}
.qs-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.task-table {
  width: 100%;
}
.op-col {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.up { color: var(--el-color-danger, #f56c6c); }
.down { color: var(--el-color-success, #67c23a); }
.muted { color: var(--el-text-color-placeholder, #c0c4cc); }

/* v55 添加任务 dialog 2 列布局 */
.add-task-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 16px;
  height: 480px;
}
.add-task-left,
.add-task-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.add-task-left {
  border-right: 1px solid var(--el-border-color-light, #ebeef5);
  padding-right: 12px;
}
.left-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  margin-bottom: 8px;
  flex-shrink: 0;
}
.add-task-right :deep(.el-dialog) {
  /* dialog 内部嵌套消除二次 dialog 包裹 */
  margin: 0;
}
</style>