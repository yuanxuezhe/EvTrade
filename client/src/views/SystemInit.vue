<template>
  <div class="system-init">
    <h2>系统初始化</h2>

    <!-- 当前交易日状态 -->
    <el-card class="status-card" shadow="hover">
      <template #header>
        <span class="card-title">📅 当前交易日</span>
      </template>
      <div v-loading="loading.current">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="状态">
            <el-tag v-if="currentDay?.status === 'active'" type="success">活跃</el-tag>
            <el-tag v-else-if="currentDay?.status === 'pending'" type="warning">未激活</el-tag>
            <el-tag v-else-if="currentDay?.status === 'closed'" type="info">已收盘</el-tag>
            <el-tag v-else type="info">未知</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="交易日">
            {{ currentDay?.trd_date || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="服务器时间">
            {{ clock.now }}
          </el-descriptions-item>
          <el-descriptions-item label="交易时段">
            <el-tag v-if="clock.in_session" type="success" size="small">交易中</el-tag>
            <el-tag v-else type="danger" size="small">休市</el-tag>
            {{ clock.session_label }}
          </el-descriptions-item>
          <el-descriptions-item label="激活于">
            {{ currentDay?.activated_at || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="最近对账">
            {{ currentDay?.last_reconcile_at || '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-card>

    <!-- 触发日初 -->
    <el-card class="action-card" shadow="hover">
      <template #header>
        <span class="card-title">🚀 触发日初处理</span>
      </template>
      <el-alert
        title="日初处理 = 调柜台拉取数据对账 + 激活新交易日"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form :model="initForm" label-width="120px" style="margin-top: 16px">
        <el-form-item label="新交易日">
          <el-date-picker
            v-model="initForm.date"
            type="date"
            value-format="YYYYMMDD"
            format="YYYY-MM-DD"
            placeholder="选择要激活的交易日"
            style="width: 240px"
          />
        </el-form-item>
        <el-form-item label="对账模式">
          <el-radio-group v-model="initForm.mode">
            <el-radio value="auto">自动（推荐）</el-radio>
            <el-radio value="manual">手动（生成报告但不应用）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading.init"
            :disabled="!initForm.date"
            @click="handleInit"
          >
            触发日初
          </el-button>
          <el-button
            :loading="loading.reconcile"
            @click="handleReconcile"
          >
            仅生成对账报告
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 配置面板（已迁出 → SystemConfig.vue，v6.5 拆分） -->
    <el-card class="config-link-card" shadow="hover">
      <el-button type="primary" @click="$router.push('/system-config')">
        <el-icon class="el-icon--right"><Setting /></el-icon>
        前往系统配置（对账/时段/费率）
      </el-button>
    </el-card>

    <!-- 历史报告 -->
    <el-card class="reports-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">📋 历史对账报告</span>
          <el-button :loading="loading.reports" size="small" @click="loadReports">
            刷新
          </el-button>
        </div>
      </template>
      <el-table :data="reports" v-loading="loading.reports" stripe>
        <el-table-column prop="trd_date" label="交易日" width="120" />
        <el-table-column prop="mode" label="模式" width="100">
          <template #default="{ row }">
            <el-tag :type="row.mode === 'auto' ? 'success' : 'info'" size="small">
              {{ row.mode }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rpc_status" label="RPC 状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.rpc_status === 'ok' ? 'success' :
                     row.rpc_status === 'partial' ? 'warning' : 'danger'"
              size="small"
            >
              {{ row.rpc_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误信息" />
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="viewReport(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 报告详情 -->
    <el-dialog v-model="reportDialog" title="对账报告详情" width="700px">
      <pre class="report-body">{{ reportDetail }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import { sysStatusApi, reconcileApi } from '../api/admin'
import { http } from '../api'

const loading = reactive({
  current: false,
  init: false,
  reconcile: false,
  reports: false
})

const currentDay = ref(null)
const reports = ref([])
const reportDialog = ref(false)
const reportDetail = ref('')

const initForm = reactive({
  date: '',
  mode: 'auto'
})

const clock = reactive({ now: '', in_session: false, session_label: '' })
let _tickHandle = null

function tickClock() {
  const d = new Date()
  clock.now = d.toLocaleString('zh-CN', { hour12: false })
  const h = d.getHours(), m = d.getMinutes()
  const t = h * 60 + m
  const ms = 9 * 60 + 15, me = 11 * 60 + 30
  const as = 13 * 60, ae = 15 * 60
  if (t >= ms && t <= me) { clock.in_session = true; clock.session_label = '上午' }
  else if (t >= as && t <= ae) { clock.in_session = true; clock.session_label = '下午' }
  else { clock.in_session = false; clock.session_label = '休市' }
}

async function loadCurrent() {
  loading.current = true
  try {
    const data = await sysStatusApi.current()
    currentDay.value = data
  } catch (e) {
    currentDay.value = null
  } finally {
    loading.current = false
  }
}

async function loadReports() {
  loading.reports = true
  try {
    reports.value = await reconcileApi.listReports()
  } catch (e) {
    reports.value = []
  } finally {
    loading.reports = false
  }
}

async function handleInit() {
  if (!initForm.date) {
    ElMessage.warning('请先选择交易日')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认激活 ${initForm.date} 作为新交易日？将调柜台对账 + 切日`,
      '触发日初',
      { type: 'warning' }
    )
  } catch { return }

  loading.init = true
  try {
    const result = await sysStatusApi.init(initForm.date)
    if (result.code === 0 || result.ok) {
      ElMessage.success(`日初成功：${result.report_id || ''}`)
      loadCurrent()
      loadReports()
    } else {
      ElMessage.error(`日初失败：${result.msg || '未知错误'}（报告 #${result.report_id}）`)
    }
  } catch (e) {
    ElMessage.error('日初失败：' + (e.msg || e.message))
  } finally {
    loading.init = false
  }
}

async function handleReconcile() {
  if (!initForm.date) {
    ElMessage.warning('请先选择交易日')
    return
  }
  loading.reconcile = true
  try {
    const result = await sysStatusApi.init(initForm.date, 'manual')
    if (result.code === 0 || result.ok) {
      ElMessage.success(`对账报告已生成：#${result.report_id || ''}`)
      loadReports()
    } else {
      ElMessage.error(`对账失败：${result.msg || result.error || '未知错误'}`)
    }
  } catch (e) {
    ElMessage.error('对账失败：' + (e.msg || e.message))
  } finally {
    loading.reconcile = false
  }
}

async function viewReport(row) {
  try {
    // v5: 复合主键 (trd_date, mode, created_at)
    const data = await reconcileApi.getReport(row.trd_date, row.mode, row.created_at)
    reportDetail.value = JSON.stringify(data, null, 2)
    reportDialog.value = true
  } catch (e) {
    ElMessage.error('加载报告失败')
  }
}

onMounted(() => {
  loadCurrent()
  loadReports()
  tickClock()
  _tickHandle = setInterval(tickClock, 1000)
})
onUnmounted(() => {
  if (_tickHandle) clearInterval(_tickHandle)
})
</script>

<style scoped>
.system-init { padding: 16px; }
h2 { margin: 0 0 16px 0; }
.status-card, .action-card, .config-card, .reports-card {
  margin-bottom: 16px;
}
.card-title { font-weight: 600; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.hint { color: #909399; font-size: 12px; margin-left: 8px; }
.report-body {
  max-height: 500px;
  overflow: auto;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
}
</style>
