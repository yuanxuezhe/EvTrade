<template>
  <div class="admin-sync fade-in-up">
    <!-- 顶部状态卡 -->
    <section class="stats-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">同步任务状态</h3>
            <p class="panel-sub">东方财富股票基础信息爬虫 (v21)</p>
          </div>
          <el-tag
            :type="stateTagType"
            :effect="isRunning ? 'dark' : 'plain'"
            size="small"
          >
            {{ stateLabel }}
          </el-tag>
        </div>

        <div class="status-row">
          <el-button
            v-if="!isRunning"
            type="primary"
            :icon="VideoPlay"
            :loading="starting"
            @click="onStart"
          >
            启动同步
          </el-button>
          <el-button
            v-else
            type="danger"
            :icon="VideoPause"
            @click="onStop"
          >
            停止
          </el-button>
          <el-button :icon="Refresh" @click="onRefresh" :disabled="isRunning">
            刷新
          </el-button>
          <span class="ws-indicator" :class="{ on: wsConnected }">
            <el-icon><Connection /></el-icon>
            WS {{ wsConnected ? '已连接' : '未连接' }}
          </span>
        </div>

        <!-- 进度条 -->
        <div v-if="task" class="progress-block">
          <el-progress
            :percentage="percent"
            :status="progressStatus"
            :stroke-width="14"
            :text-inside="true"
          />
          <div class="progress-meta">
            <span>
              进度 <strong class="text-mono">{{ task.processed ?? 0 }}</strong>
              / <strong class="text-mono">{{ task.total }}</strong>
              <span v-if="currentCode" class="current-code">
                · 当前：<strong class="text-mono">{{ currentCode }}</strong>
              </span>
              <span v-if="etaSec != null" class="eta">
                · 预计剩余 <strong class="text-mono">{{ formatEta(etaSec) }}</strong>
              </span>
            </span>
          </div>
        </div>
        <el-empty v-else description="暂无同步任务" :image-size="80" />
      </div>

      <!-- 计数卡 -->
      <div class="content-card panel">
        <div class="panel-header">
          <h3 class="panel-title">本次结果</h3>
        </div>
        <div class="counter-grid">
          <div class="counter">
            <div class="counter-label">新增</div>
            <div class="counter-value text-mono text-up">{{ task?.inserted ?? 0 }}</div>
          </div>
          <div class="counter">
            <div class="counter-label">更新</div>
            <div class="counter-value text-mono text-warning">{{ task?.updated ?? 0 }}</div>
          </div>
          <div class="counter">
            <div class="counter-label">跳过</div>
            <div class="counter-value text-mono text-secondary">{{ task?.skipped ?? 0 }}</div>
          </div>
          <div class="counter">
            <div class="counter-label">失败</div>
            <div class="counter-value text-mono text-down">{{ task?.failed ?? 0 }}</div>
          </div>
        </div>
        <div v-if="task" class="task-meta">
          <div><span class="text-secondary">任务 ID：</span><span class="text-mono">{{ task.job_id }}</span></div>
          <div v-if="task.started_at"><span class="text-secondary">开始：</span>{{ formatTime(task.started_at) }}</div>
          <div v-if="task.finished_at"><span class="text-secondary">结束：</span>{{ formatTime(task.finished_at) }}</div>
        </div>
      </div>
    </section>

    <!-- 错误明细 -->
    <section v-if="errors.length > 0" class="content-card panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">错误明细</h3>
          <p class="panel-sub">最近 {{ errors.length }} 条</p>
        </div>
        <el-button size="small" :icon="Delete" @click="errors.splice(0, errors.length)">清空</el-button>
      </div>
      <el-table :data="[...errors].reverse()" max-height="320" size="small" :show-header="true">
        <el-table-column prop="stock_code" label="代码" width="140" />
        <el-table-column prop="error" label="错误信息" />
        <el-table-column prop="ts" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.ts) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
/**
 * /admin/sync 页面 (v21 stock-info-crawler)
 *
 * - 调 useSyncStore.start/stop 触发同步
 * - WS /ws/sync_update 通过 ws_dispatch._onSync* 路由到 store
 * - 单文件可独立访问（不依赖 router/菜单，直接 URL /admin/sync 即可）
 */
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, VideoPause, Refresh, Delete, Connection } from '@element-plus/icons-vue'
import { useSyncStore } from '../stores/sync'

const syncStore = useSyncStore()

// reactive 转发（template 直接用 store.xxx 不需要 .value）
const task = computed(() => syncStore.task)
const errors = computed(() => syncStore.errors)
const wsConnected = computed(() => syncStore.wsConnected)
const isRunning = computed(() => syncStore.isRunning)
const percent = computed(() => syncStore.percent)
const currentCode = computed(() => syncStore.currentCode)
const etaSec = computed(() => syncStore.etaSec)
const starting = ref(false)

import { ref } from 'vue'

const stateLabel = computed(() => {
  const s = task.value?.state
  if (!s) return '空闲'
  return {
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    stopping: '停止中',
    stopped: '已停止'
  }[s] || s
})

const stateTagType = computed(() => {
  const s = task.value?.state
  if (s === 'running') return 'success'
  if (s === 'completed') return 'info'
  if (s === 'failed') return 'danger'
  if (s === 'stopping' || s === 'stopped') return 'warning'
  return 'info'
})

const progressStatus = computed(() => {
  const s = task.value?.state
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'exception'
  return undefined
})

function formatEta(sec) {
  if (sec == null) return '--'
  if (sec < 60) return `${Math.round(sec)}s`
  return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
}

function formatTime(s) {
  if (!s) return '--'
  try {
    return new Date(s).toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return s
  }
}

async function onStart() {
  starting.value = true
  try {
    const res = await syncStore.start()
    ElMessage.success(res.message || `已启动同步任务 (${res.total} 只)`)
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error(msg)
  } finally {
    starting.value = false
  }
}

async function onStop() {
  try {
    const res = await syncStore.stop()
    ElMessage.success(res.stopped ? '已停止' : '停止请求已发送')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

async function onRefresh() {
  await syncStore.refreshStatus()
}

// 订阅 ws_dispatch 的 sync_update 频道（动态 import 避免循环依赖）
let _unsubscribeWs = null
onMounted(async () => {
  await syncStore.refreshStatus()
  try {
    const wsDispatch = await import('../stores/ws_dispatch')
    _unsubscribeWs = wsDispatch.subscribeSync()
    syncStore.setWsConnected(true)
  } catch (e) {
    console.warn('[AdminSync] ws subscribe failed:', e?.message)
  }
})

onBeforeUnmount(() => {
  if (typeof _unsubscribeWs === 'function') {
    _unsubscribeWs()
  }
})
</script>

<style scoped>
.admin-sync {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.stats-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: var(--space-5);
}

.panel {
  padding: var(--space-5);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-4);
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.ws-indicator {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}
.ws-indicator.on {
  color: var(--color-up);
}

.progress-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.progress-meta {
  font-size: 13px;
  color: var(--text-regular);
}

.current-code,
.eta {
  margin-left: var(--space-2);
}

.counter-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
}

.counter {
  text-align: center;
  padding: var(--space-3);
  background: var(--bg-soft);
  border-radius: var(--radius-base);
}

.counter-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.counter-value {
  font-size: 22px;
  font-weight: 600;
  margin-top: 4px;
}

.text-up { color: var(--color-up); }
.text-down { color: var(--color-down); }
.text-warning { color: var(--color-warning, #e6a23c); }

.task-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-regular);
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
</style>