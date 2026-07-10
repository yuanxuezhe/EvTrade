import { defineStore } from 'pinia'
import { reactive, ref, computed } from 'vue'
import { syncApi } from '../api/sync'

/**
 * 同步任务状态缓存（v21 stock-info-crawler）
 *
 * 数据源：
 *   1. REST GET /api/sync/stocks/status — 启动时拿一次 + 启动/停止后刷新
 *   2. WS /ws/sync_update — 订阅 progress 帧自动更新（增量，不轮询）
 *
 * WS 消息类型：
 *   - {type: 'sync_progress', data: {job_id, processed, total, current_code, eta_sec}}
 *   - {type: 'sync_started', data: {job_id, total, already_existed}}
 *   - {type: 'sync_completed', data: {job_id, processed, inserted, updated, skipped, failed}}
 *   - {type: 'sync_failed', data: {job_id, error}}
 *   - {type: 'sync_stopped', data: {job_id}}
 */
export const useSyncStore = defineStore('sync', () => {
  // 当前任务状态（REST 返回的 shape）
  const task = ref(null)
  // WS 实时进度（覆盖 task.current_code / eta_sec / processed）
  const liveProgress = reactive({})
  // WS 错误明细（最近 100 条）
  const errors = reactive([])
  // ws 连接状态（仅用于 UI 提示，不影响数据正确性）
  const wsConnected = ref(false)

  /** 启动同步（调 REST,然后等 WS 推送） */
  async function start() {
    const res = await syncApi.start()
    // 启动后立即拉一次 status（兜底，WS 还没来的话）
    await refreshStatus()
    return res
  }

  /** 停止当前同步 */
  async function stop() {
    const res = await syncApi.stop()
    await refreshStatus()
    return res
  }

  /** 从 REST 拉状态（兜底） */
  async function refreshStatus() {
    try {
      const s = await syncApi.status()
      task.value = s
      // 同步 errors（REST 返回的是累计的）
      if (s && Array.isArray(s.errors)) {
        errors.splice(0, errors.length, ...s.errors.slice(-100))
      }
      return s
    } catch (e) {
      console.warn('[syncStore] refreshStatus failed:', e?.message)
      return null
    }
  }

  // ===== WS 事件处理（由 ws_dispatch 调）=====

  function onSyncStarted(data) {
    task.value = {
      job_id: data.job_id,
      state: 'running',
      total: data.total,
      processed: 0,
      inserted: 0,
      updated: 0,
      skipped: 0,
      failed: 0,
      current_code: null,
      eta_sec: null,
      started_at: new Date().toISOString(),
      finished_at: null,
      errors: []
    }
    liveProgress.processed = 0
    liveProgress.current_code = null
    errors.splice(0, errors.length)
  }

  function onSyncProgress(data) {
    if (!task.value || task.value.job_id !== data.job_id) return
    // REST 返的是累计 processed/inserted/updated/skipped/failed，progress 不重发
    // 只覆盖 current_code + eta_sec
    liveProgress.current_code = data.current_code || null
    liveProgress.eta_sec = data.eta_sec ?? null
    liveProgress.processed = data.processed ?? task.value.processed
  }

  function onSyncCompleted(data) {
    if (!task.value || task.value.job_id !== data.job_id) return
    task.value.state = 'completed'
    task.value.processed = data.processed ?? task.value.processed
    task.value.inserted = data.inserted ?? task.value.inserted
    task.value.updated = data.updated ?? task.value.updated
    task.value.skipped = data.skipped ?? task.value.skipped
    task.value.failed = data.failed ?? task.value.failed
    task.value.finished_at = new Date().toISOString()
    liveProgress.current_code = null
    liveProgress.eta_sec = null
  }

  function onSyncFailed(data) {
    if (!task.value || task.value.job_id !== data.job_id) return
    task.value.state = 'failed'
    task.value.finished_at = new Date().toISOString()
    if (data.error) {
      errors.push({
        stock_code: data.stock_code || '(task)',
        error: data.error,
        ts: new Date().toISOString()
      })
    }
  }

  function onSyncStopped(data) {
    if (!task.value || task.value.job_id !== data.job_id) return
    task.value.state = 'stopped'
    task.value.finished_at = new Date().toISOString()
  }

  function onStockSynced(data) {
    // 单只同步完成的实时计数（供 UI 立即看到插入/更新）
    if (!task.value) return
    if (data.action === 'inserted') task.value.inserted += 1
    else if (data.action === 'updated') task.value.updated += 1
    else if (data.action === 'skipped') task.value.skipped += 1
    else if (data.action === 'failed' && data.error) {
      errors.push({
        stock_code: data.stock_code,
        error: data.error,
        ts: new Date().toISOString()
      })
    }
  }

  function setWsConnected(v) {
    wsConnected.value = !!v
  }

  // 计算属性
  const isRunning = computed(() => task.value?.state === 'running')
  const isFinished = computed(() =>
    ['completed', 'failed', 'stopped'].includes(task.value?.state)
  )
  const percent = computed(() => {
    if (!task.value || !task.value.total) return 0
    const done = (task.value.processed ?? liveProgress.processed ?? 0)
    return Math.min(100, Math.round((done / task.value.total) * 100))
  })
  const currentCode = computed(() => liveProgress.current_code || task.value?.current_code || null)
  const etaSec = computed(() => liveProgress.eta_sec ?? task.value?.eta_sec ?? null)

  return {
    task, liveProgress, errors, wsConnected,
    start, stop, refreshStatus,
    onSyncStarted, onSyncProgress, onSyncCompleted, onSyncFailed, onSyncStopped,
    onStockSynced, setWsConnected,
    isRunning, isFinished, percent, currentCode, etaSec,
  }
})