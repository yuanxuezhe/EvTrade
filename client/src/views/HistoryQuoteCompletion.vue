<template>
  <div class="his-quote-backfill fade-in-up" :style="rootStyle">
    <!-- 工具栏 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <span class="hint">
          按日补全历史分钟行情（从「已加载日期 +1」到昨天，逐日拉取落地 minute_bars）
        </span>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" :loading="loading" @click="onRefresh">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="onAddOpen">新增任务</el-button>
      </div>
    </div>

    <!-- 主表: 行情同步任务表 -->
    <div class="content-card table-wrap" v-loading="loading">
      <DataTableView
        :columns="columns"
        :data="rows"
        row-key="stock_code"
        :empty-description="'无补全任务，点「新增任务」添加证券'"
        :no-pagination="true"
      >
        <template #column-stock_code="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
        </template>
        <template #column-time_range="{ row }">
          <span class="text-mono">
            {{ row.start_date }} ~ {{ row.end_date ? row.end_date : '昨天(开放)' }}
          </span>
        </template>
        <template #column-last_loaded_date="{ row }">
          <span class="text-mono">{{ row.last_loaded_date || '未开始' }}</span>
        </template>
        <template #column-auto_sync="{ row }">
          <el-switch
            :model-value="!!row.auto_sync"
            :loading="!!_rs(row).busy"
            @change="(v) => onToggleAuto(row, v)"
          />
        </template>
        <template #column-status="{ row }">
          <div class="status-cell">
            <template v-if="_rs(row).busy">
              <el-icon class="spin" :size="16"><Loading /></el-icon>
              <span class="txt">同步中 {{ _rs(row).day || '' }}</span>
            </template>
            <template v-else-if="_rs(row).fail">
              <el-tag type="danger" size="small">失败</el-tag>
            </template>
            <template v-else-if="_rs(row).done">
              <el-tag type="success" size="small">已完成</el-tag>
            </template>
            <template v-else>
              <el-tag type="info" size="small">{{ row.status === 'failed' ? '失败' : (row.status || '未开始') }}</el-tag>
            </template>
            <el-tooltip
              v-if="_rs(row).fail || row.error_msg"
              :content="(_rs(row).fail || row.error_msg || '').slice(0, 200)"
              placement="top"
            >
              <span class="err">原因</span>
            </el-tooltip>
          </div>
        </template>
        <template #column-action="{ row }">
          <el-button size="small" link type="primary" :disabled="_rs(row).busy" @click.stop="onRun(row)">
            {{ _rs(row).busy ? '补全中…' : '补全' }}
          </el-button>
          <el-button size="small" link type="danger" :disabled="_rs(row).busy" @click.stop="onRemove(row)">
            删除
          </el-button>
        </template>
      </DataTableView>
    </div>

    <!-- 新增任务 dialog -->
    <el-dialog v-model="addVisible" title="新增补全任务" width="460px" :close-on-click-modal="false">
      <el-form ref="addFormRef" :model="addForm" :rules="addRules" label-width="110px">
        <el-form-item label="证券代码" prop="stock_code">
          <el-input v-model="addForm.stock_code" placeholder="例如 159992.SZ" maxlength="16" />
        </el-form-item>
        <el-form-item label="开始日期" prop="start_date">
          <el-date-picker
            v-model="addForm.start_date"
            type="date"
            value-format="YYYYMMDD"
            placeholder="选择开始日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-date-picker
            v-model="addForm.end_date"
            type="date"
            value-format="YYYYMMDD"
            placeholder="留空=补到昨天(开放)"
            clearable
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="自动同步">
          <el-switch v-model="addForm.auto_sync" />
          <span class="hint">启动时自动增量补平（默认开）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="addSaving" @click="onAddSave">保存并补全</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Loading } from '@element-plus/icons-vue'
import DataTableView from '../components/DataTableView.vue'
import { COL } from '../utils/tableColumns'
import { useUiStore } from '../stores/ui'
import { quoteSyncApi } from '../api/quote_sync'

const uiStore = useUiStore()
const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))

const loading = ref(false)
const rows = ref([])

// 每行运行态: {busy, day, fail, done} (存前端, 不落库)
const rowState = ref({})
const _rs = (row) => (rowState.value[row.stock_code] ||= { busy: false, day: '', fail: '', done: false })

// 串行队列: 同一时刻只补一只证券, 避免同时压 broker
let _queue = Promise.resolve()
let _unmounted = false

const columns = [
  { key: 'stock_code', label: '证券代码', vBind: COL.STOCK_CODE },
  { key: 'time_range', label: '时间区间', width: 210, sortable: false },
  { key: 'last_loaded_date', label: '当前已加载到的日期', width: 170, sortable: false },
  { key: 'auto_sync', label: '自动同步', width: 90, align: 'center', headerAlign: 'center', sortable: false },
  { key: 'status', label: '状态', minWidth: 180, sortable: false },
  { key: 'action', label: '操作', width: 150, fixed: 'right', align: 'center', sortable: false },
]

function _yesterday() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
}
function _nextDay(day) {
  const d = new Date(`${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6, 8)}`)
  d.setDate(d.getDate() + 1)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
}

async function loadRows() {
  loading.value = true
  try {
    const body = await quoteSyncApi.list()
    rows.value = body?.list || body || []
  } catch (e) {
    ElMessage.error('加载失败: ' + (e?.msg || e?.message || e))
  } finally {
    loading.value = false
  }
}

function onRefresh() { return loadRows() }

// 串行入队补全单只证券 (按日循环)
function enqueueRun(row) {
  _queue = _queue.then(() => runBackfill(row.stock_code)).catch(() => {})
}

async function runBackfill(stockCode) {
  if (_unmounted) return
  const cfg = rows.value.find((r) => r.stock_code === stockCode)
  if (!cfg) return
  const rs = _rs(cfg)
  const cap = cfg.end_date ? (cfg.end_date < _yesterday() ? cfg.end_date : _yesterday()) : _yesterday()
  // 从「已加载日期 + 1」补到 cap (根据 minute_bars 已有记录, 后端 last_loaded 即实际最大日期)
  let day = _nextDay(cfg.last_loaded_date || cfg.start_date)
  rs.busy = true
  rs.fail = ''
  rs.done = false
  try {
    while (day <= cap && !_unmounted) {
      rs.day = day
      const r = await quoteSyncApi.syncDay(stockCode, day)
      if (_unmounted) return
      if (r && Number(r.code) === 0) {
        cfg.last_loaded_date = r.last_loaded_date || day
        cfg.status = 'success'
        cfg.error_msg = ''
        day = _nextDay(day)
      } else {
        // 失败: 停止, 显示原因 (后端已记 status=failed + error_msg)
        rs.fail = (r && r.msg) || '同步失败'
        cfg.status = 'failed'
        cfg.error_msg = rs.fail
        break
      }
    }
    if (!_unmounted) rs.done = true
  } catch (e) {
    rs.fail = e?.msg || e?.message || '同步失败'
    cfg.status = 'failed'
    cfg.error_msg = rs.fail
  } finally {
    rs.busy = false
    rs.day = ''
    loadRows().catch(() => {})
  }
}

function onRun(row) {
  enqueueRun(row)
}

async function onToggleAuto(row, v) {
  try {
    await quoteSyncApi.patch(row.stock_code, { auto_sync: v ? 1 : 0 })
    row.auto_sync = v ? 1 : 0
    ElMessage.success(`已${v ? '启用' : '停用'} ${row.stock_code} 自动同步`)
  } catch (e) {
    ElMessage.error('切换失败: ' + (e?.msg || e?.message || e))
  }
}

async function onRemove(row) {
  try {
    await ElMessageBox.confirm(
      `删除 ${row.stock_code} 的补全配置？（已落地的 minute_bars 数据不会删）`,
      '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    await quoteSyncApi.remove(row.stock_code)
    ElMessage.success('已删除')
    await loadRows()
  } catch (e) {
    ElMessage.error('删除失败: ' + (e?.msg || e?.message || e))
  }
}

// ==================== 新增任务 ====================
const addVisible = ref(false)
const addSaving = ref(false)
const addFormRef = ref(null)
const addForm = reactive({ stock_code: '', start_date: '', end_date: '', auto_sync: true })

const addRules = {
  stock_code: [
    { required: true, message: '请输入证券代码', trigger: 'blur' },
    { pattern: /^\d{6}\.(SH|SZ|BJ)$/, message: '格式 6位数字+.SH/.SZ/.BJ (例 159992.SZ)', trigger: 'blur' },
  ],
  start_date: [{ required: true, message: '请选择开始日期', trigger: 'change' }],
}

function onAddOpen() {
  addForm.stock_code = ''
  addForm.start_date = ''
  addForm.end_date = _yesterday()  // 默认结束日期 = 昨天 (今天数据不全)
  addForm.auto_sync = true
  addFormRef.value?.clearValidate()
  addVisible.value = true
}

async function onAddSave() {
  try { await addFormRef.value?.validate() } catch { return }
  if (!addForm.start_date) { ElMessage.warning('请选择开始日期'); return }
  addSaving.value = true
  try {
    const data = await quoteSyncApi.add({
      stock_code: addForm.stock_code.trim(),
      start_date: addForm.start_date,
      end_date: addForm.end_date || '',
      auto_sync: addForm.auto_sync ? 1 : 0,
    })
    ElMessage.success(`已添加 ${addForm.stock_code}（按已有记录自动补全）`)
    addVisible.value = false
    await loadRows()
    // 新增后自动开始补全
    const cfg = rows.value.find((r) => r.stock_code === addForm.stock_code.trim())
    if (cfg && data?.auto_sync !== 0) enqueueRun(cfg)
  } catch (e) {
    ElMessage.error('添加失败: ' + (e?.msg || e?.response?.data?.detail || e?.message || e))
  } finally {
    addSaving.value = false
  }
}

onMounted(async () => {
  await loadRows()
  // 启动自动补全: auto_sync=1 且未追平的证券 (串行)
  const y = _yesterday()
  for (const row of rows.value) {
    if (_unmounted) break
    if (row.auto_sync && (row.last_loaded_date || '') < y) {
      enqueueRun(row)
    }
  }
})

onBeforeUnmount(() => { _unmounted = true })
</script>

<style scoped>
.his-quote-backfill { display: flex; flex-direction: column; gap: var(--space-4); height: calc(100% - var(--oplog-extra, 0px)); min-height: 0; overflow: hidden; }
.filter-bar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-3) var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.filter-left, .filter-right { display: flex; gap: var(--space-2); align-items: center; }
.hint { color: #909399; font-size: 12px; }
.table-wrap { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }
.status-cell { display: flex; align-items: center; gap: 6px; }
.status-cell .spin { color: var(--el-color-primary, #409eff); animation: rot 1s linear infinite; }
@keyframes rot { from { transform: rotate(0); } to { transform: rotate(360deg); } }
.status-cell .txt { font-size: 12px; color: #606266; }
.status-cell .err { font-size: 12px; color: var(--el-color-danger, #f56c6c); cursor: help; border-bottom: 1px dashed currentColor; }
.text-mono { font-family: var(--font-mono, 'Consolas', monospace); }
.tp-stock-code { font-family: var(--font-mono); font-weight: 600; }
</style>
