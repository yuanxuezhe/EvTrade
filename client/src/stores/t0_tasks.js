/**
 * t0_tasks.js — T0Task 缓存 store（v18 change t0-task-management）
 *
 * 📖 详见 `openspec/specs/trading/spec.md` §REQ-TRADE-013~018
 *
 * 设计：
 * - 单一权威缓存：tasks[] (Ref<Array>) + lastUpdated + cacheLoading
 * - 不持有派生 summary（实时由 t0StatsApi/aggregate 计算），避免双源漂移
 * - 视图层从 store 读 computed activeTasks / stockCodeTasks
 * - 不在视图层直接调 api
 *
 * 视图层约定：
 *   - T0TaskList.vue / T0TaskDetail.vue 从 store 读 tasks + 调用对应 action
 *   - T0Trade.vue 集成 task 下拉
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { t0TasksApi } from '../api/t0_tasks'

export const useT0TasksStore = defineStore('t0_tasks', () => {
  // ---- State -----------------------------------------------------------
  /** @type {import('vue').Ref<Array<Object>>} task 列表（每次 loadTasks 后整体覆盖） */
  const tasks = ref([])
  /** @type {import('vue').Ref<Record<number, Object>>} task by id */
  const tasksById = ref({})
  /** @type {import('vue').Ref<Array>} overall overview {overall, by_stock} */
  const overviewData = ref({ overall: {}, by_stock: [] })

  // ---- 运行时状态 -------------------------------------------------------
  const loading = ref(false)
  const error = ref(null)
  const lastUpdated = ref(0)

  // ---- Getters ----------------------------------------------------------
  /** 仅 active 状态的 task（T0Trade.vue 下拉默认源） */
  const activeTasks = computed(() =>
    tasks.value.filter((t) => t.status === 'active')
  )
  /** 按 stock_code 索引（同一只券可能有多个 task，比如分批） */
  const tasksByStockCode = computed(() => {
    const m = {}
    for (const t of tasks.value) {
      const k = t.stock_code
      if (!m[k]) m[k] = []
      m[k].push(t)
    }
    return m
  })

  // ---- Actions ----------------------------------------------------------
  /**
   * 加载 task 列表 + overview（一次拉全；前端 100 个规模内优化）
   * @param {{status?: string, stock_code?: string}} [opts]
   */
  async function loadTasks(opts = {}) {
    loading.value = true
    error.value = null
    try {
      const [list, overview] = await Promise.all([
        t0TasksApi.list(opts),
        t0TasksApi.overview(),
      ])
      tasks.value = list || []
      // 重新建 tasksById 索引
      const m = {}
      for (const t of tasks.value) m[t.id] = t
      tasksById.value = m
      overviewData.value = overview || { overall: {}, by_stock: [] }
      lastUpdated.value = Date.now()
    } catch (e) {
      error.value = e?.msg || e?.message || '加载 task 列表失败'
    } finally {
      loading.value = false
    }
  }

  /**
   * 创建 task + 乐观插入本地缓存
   * @param {Object} params 传给 t0TasksApi.create
   * @returns {Promise<Object>} 新建 task
   */
  async function createTask(params) {
    const t = await t0TasksApi.create(params)
    if (t && t.id) {
      tasks.value.push(t)
      tasksById.value[t.id] = t
    }
    return t
  }

  /**
   * 更新 task（note/coefficient/target_volume/status）+ 同步本地缓存
   * @param {number} taskId
   * @param {Object} patch
   */
  async function updateTask(taskId, patch) {
    const t = await t0TasksApi.update(taskId, patch)
    if (t && t.id) {
      const idx = tasks.value.findIndex((x) => x.id === taskId)
      if (idx >= 0) tasks.value[idx] = t
      tasksById.value[taskId] = t
    }
    return t
  }

  /**
   * 归档 task + 本地缓存 status 改为 archived
   * @param {number} taskId
   */
  async function archiveTask(taskId) {
    await t0TasksApi.remove(taskId)
    const t = tasksById.value[taskId]
    if (t) t.status = 'archived'
  }

  /**
   * 配平建议（不实际下单）
   * @param {number} taskId
   */
  async function balanceTask(taskId) {
    return await t0TasksApi.balance(taskId, true)
  }

  /**
   * 一键平仓（实际下单）
   * @param {number} taskId
   * @returns {Promise<Object>} {action, volume, ...}
   */
  async function closeTask(taskId) {
    return await t0TasksApi.close(taskId)
  }

  /**
   * 清缓存（用于登出或 view unmount）
   */
  function clearCache() {
    tasks.value = []
    tasksById.value = {}
    overviewData.value = { overall: {}, by_stock: [] }
    lastUpdated.value = 0
  }

  return {
    // state
    tasks,
    tasksById,
    overviewData,
    loading,
    error,
    lastUpdated,
    // getters
    activeTasks,
    tasksByStockCode,
    // actions
    loadTasks,
    createTask,
    updateTask,
    archiveTask,
    balanceTask,
    closeTask,
    clearCache,
  }
})
