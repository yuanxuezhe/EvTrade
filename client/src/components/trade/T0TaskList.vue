<!--
  T0TaskList.vue — T0Task 列表 + 操作按钮（v18 change t0-task-management）

  Props:
    visible (Boolean) — 控制面板是否可见（默认 true，T0Trade 中内嵌）
    embedding (String) — 'inline' | 'drawer'，决定布局（默认 inline）

  Emits:
    select(taskId)   — 用户点击查看详情（外层路由到 T0TaskDetail）
    create()         — 触发新建弹窗
    balance(taskId)  — 触发配平（外层调 store.balanceTask）
    close(taskId)    — 触发一键平仓（外层调 store.closeTask）

  行为：
    - 加载时调 store.loadTasks
    - 行展示：stock_code + 配平公式 = base+target / 当前 task_net_volume / 已实现 pnl
    - 状态徽章：active(蓝) / closed(灰) / archived(更暗)
    - 行尾操作：配平 / 平仓 / 编辑 note / 归档
-->
<template>
  <div class="t0-task-list" :class="{ 't0-task-list--drawer': embedding === 'drawer' }">
    <div class="ttl-header">
      <span class="ttl-title">📋 T0 任务</span>
      <div class="ttl-ops">
        <el-button size="small" @click="$emit('create')" type="primary">新建任务</el-button>
        <el-button size="small" @click="onRefresh" :loading="loading">刷新</el-button>
      </div>
    </div>

    <!-- 整体 / 单券双视图 -->
    <div class="ttl-overview">
      <div class="ovr-pill" data-pill="total-realized">
        <span class="ovr-label">整体已实现</span>
        <span class="ovr-value text-mono" :class="overviewClass">
          ¥{{ formatAmount(overview.total_realized_pnl || 0) }}
        </span>
      </div>
      <div class="ovr-pill" data-pill="active-count">
        <span class="ovr-label">活跃 task</span>
        <span class="ovr-value text-mono">{{ overview.active_task_count ?? tasks.length }}</span>
      </div>
      <div class="ovr-pill" data-pill="win-rate">
        <span class="ovr-label">胜率</span>
        <span class="ovr-value text-mono">
          {{ ((overview.avg_win_rate || 0) * 100).toFixed(1) }}%
        </span>
      </div>
    </div>

    <!-- list -->
    <el-table
      v-loading="loading"
      :data="filteredTasks"
      size="small"
      stripe
      empty-text="暂无 T0 任务，点击「新建任务」创建"
      class="ttl-table"
    >
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="stock_code" label="股票代码" width="120" />

      <el-table-column label="配平 (base+target)" width="160">
        <template #default="{ row }">
          <span class="text-mono">
            {{ row.base_volume }} + {{ row.target_volume }} = <b>{{ row.base_volume + row.target_volume }}</b>
          </span>
        </template>
      </el-table-column>

      <el-table-column label="task 净开仓" width="110">
        <template #default="{ row }">
          <span class="text-mono">{{ row.task_net_volume ?? '—' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="当前持仓" width="100">
        <template #default="{ row }">
          <span class="text-mono">{{ row.position_vol ?? '—' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="已实现盈亏" width="130">
        <template #default="{ row }">
          <span class="text-mono" :class="pnlClass(row.realized_pnl)">
            ¥{{ formatAmount(row.realized_pnl || 0) }}
          </span>
        </template>
      </el-table-column>

      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />

      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'active'" size="small" link @click="$emit('balance', row.id)">配平</el-button>
          <el-button v-if="row.status === 'active'" size="small" link @click="$emit('close', row.id)">平仓</el-button>
          <el-button size="small" link @click="onEditNote(row)">编辑</el-button>
          <el-button v-if="row.status !== 'archived'" size="small" link type="danger" @click="onArchive(row)">归档</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 备注编辑弹出 -->
    <el-dialog v-model="editingNoteVisible" title="编辑备注" width="400px" align-center>
      <el-input v-model="editingNote" maxlength="255" show-word-limit type="textarea" :rows="3" />
      <template #footer>
        <el-button @click="editingNoteVisible = false">取消</el-button>
        <el-button type="primary" :loading="editingLoading" @click="onSaveNote">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useT0TasksStore } from '../../stores/t0_tasks'

const props = defineProps({
  embedding: { type: String, default: 'inline' }, // 'inline' | 'drawer'
  statusFilter: { type: String, default: '' },    // '' = all, 'active', 'closed', 'archived'
})
const emit = defineEmits(['create', 'balance', 'close', 'select'])

const store = useT0TasksStore()
const loading = computed(() => store.loading)
const tasks = computed(() => store.tasks)
// 后端 OverviewResponse 字段是扁平 total_realized_pnl/active_task_count/avg_win_rate (v18)
const overview = computed(() => store.overviewData || {})

const filteredTasks = computed(() => {
  if (!props.statusFilter) return tasks.value
  return tasks.value.filter((t) => t.status === props.statusFilter)
})

const overviewClass = computed(() => pnlClass(overview.value.total_realized_pnl || 0))

onMounted(() => {
  if (store.tasks.length === 0) store.loadTasks()
})

// ---------- 操作 ----------
async function onRefresh() { await store.loadTasks() }

async function onArchive(row) {
  try {
    await store.archiveTask(row.id)
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}

const editingNoteVisible = ref(false)
const editingNote = ref('')
const editingRow = ref(null)
const editingLoading = ref(false)

function onEditNote(row) {
  editingRow.value = row
  editingNote.value = row.note || ''
  editingNoteVisible.value = true
}
async function onSaveNote() {
  if (!editingRow.value) return
  editingLoading.value = true
  try {
    await store.updateTask(editingRow.value.id, { note: editingNote.value })
    editingNoteVisible.value = false
  } finally {
    editingLoading.value = false
  }
}

// ---------- helpers ----------
function statusLabel(s) {
  return s === 'active' ? '活跃' : s === 'closed' ? '已平仓' : s === 'archived' ? '已归档' : s || '—'
}
function statusTagType(s) {
  if (s === 'active') return 'primary'
  if (s === 'closed') return 'info'
  return 'danger'
}
function pnlClass(v) {
  if (v > 0) return 'pnl-pos'
  if (v < 0) return 'pnl-neg'
  return ''
}
function formatAmount(v) {
  return (Number(v) || 0).toFixed(2)
}
</script>

<style scoped>
.ttl-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.ttl-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary, #303133);
}
.ttl-ops { display: flex; gap: 6px; }

.ttl-overview {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.ovr-pill {
  display: flex;
  flex-direction: column;
  padding: 8px 14px;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  min-width: 110px;
}
.ovr-label {
  font-size: 11px;
  color: var(--el-text-color-secondary, #909399);
}
.ovr-value {
  font-size: 16px;
  font-weight: 600;
  margin-top: 2px;
}

.ttl-table { width: 100%; }
.pnl-pos { color: var(--el-color-success, #67c23a); }
.pnl-neg { color: var(--el-color-danger, #f56c6c); }

.t0-task-list--drawer { padding: 16px; }
</style>
