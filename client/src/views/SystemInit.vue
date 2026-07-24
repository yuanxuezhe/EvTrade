<template>
  <div class="system-init fade-in-up">
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
        <el-table-column prop="error_message" label="错误信息" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="viewReport(row)">查看</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="150" />
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
// change 2026-07-15-system-init-broadcast: handleInit 成功后同步刷新 holdings/asset/position
//   双保险: 即便 ws init_completed 推送丢失/未连, 用户也能立即看到新持仓
import { useHoldingsStore } from '../stores/holdings'
import { useAssetStore } from '../stores/asset'
import { usePositionStore } from '../stores/position'
// change 2026-07-15-system-init-broadcast end

// change 2026-07-21-system-init-page-refresh: 监听 ws 系统事件 'evtrade:day-init-completed'
//   - 其他 tab 或本 tab 通过 ws 收到 init_completed 时, 刷新历史报告列表
//   - 用 CustomEvent 解耦 (ws_dispatch 不直接 import view)

const loading = reactive({
  init: false,
  reconcile: false,
  reports: false
})

const reports = ref([])
const reportDialog = ref(false)
const reportDetail = ref('')

// 本机日期 YYYYMMDD
function _todayYYYYMMDD() {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

const initForm = reactive({
  date: _todayYYYYMMDD(),
  mode: 'auto'
})

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
      loadReports()
      // change 2026-07-15-system-init-broadcast: 双保险 — 即便 ws init_completed 推送丢失/未连, 也能立即刷新
      //   ws 是主路径（多 tab 自动同步）, 此处是兜底（同 tab 立即可见）
      // change 2026-07-21-system-init-page-refresh: 升级用 resetForNewDay (切日 + 清 IDB + 重 bootstrap)
      //   - 旧 refreshAll 不切 activeTrdDate 不清 IDB, 导致 Position.vue netChange / T0Trade 当前日
      //     仍显示昨日; 新路径完整切日
      try {
        const hs = useHoldingsStore()
        if (typeof hs.resetForNewDay === 'function') {
          hs.resetForNewDay()
        } else {
          hs.refreshAll()
          useAssetStore().fetchAsset()
          usePositionStore().fetchPositions()
        }
      } catch (_e) { /* store 未就绪时忽略, 不影响 HTTP 200 路径 */ }
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

// change 2026-07-21-system-init-page-refresh: ws 'evtrade:day-init-completed' 事件 handler
//   - 触发时机: ws_dispatch._onInitCompleted 收到后端 system_update 推送后
//   - 行为: loadReports 重拉历史报告 (新报告刚生成)
function _onDayInitCompleted(e) {
  loadReports()
}

onMounted(() => {
  loadReports()
  // change 2026-07-21-system-init-page-refresh: 注册 ws 系统事件监听
  if (typeof window !== 'undefined') {
    window.addEventListener('evtrade:day-init-completed', _onDayInitCompleted)
  }
})
onUnmounted(() => {
  // change 2026-07-21-system-init-page-refresh: 注销 ws 系统事件监听
  if (typeof window !== 'undefined') {
    window.removeEventListener('evtrade:day-init-completed', _onDayInitCompleted)
  }
})
</script>

<style scoped>
.system-init { padding: 16px; }
.action-card, .config-card, .reports-card {
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
