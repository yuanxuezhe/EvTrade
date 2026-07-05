/**
 * strategy.js — 策略 store Pinia facade（change strategy_trade task 10）
 *
 * 职责：
 * - 缓存策略列表 + flag 注册表 + audit（按 strategy_id 缓存）
 * - 暴露 CRUD + 控制 actions，UI 无需直接调 api
 * - 按 status / type 分组的 getters（视图 Tab 切换 + 计数）
 *
 * 视图层约定（task 12 起）：
 *   - StrategyTrade.vue / StrategyMonitor.vue 从 store 读 strategies + getters
 *   - 控制按钮（pause/resume/stop/clear_now）→ store.controlStrategy()
 *   - 不在视图层直接调 api
 *
 * WS 接入（task 12）通过 ws.js 调 store.appendAudit 写 audit 增量
 *
 * 模块拆分：
 *   - strategy.js（本文件）— Pinia facade（state + actions + getters）
 *   - strategy_helpers.js   — createPendingTracker / upsertStrategy / removeStrategy / audit helpers
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { strategyApi } from '../api/strategy'
import {
  createPendingTracker,
  upsertStrategy, removeStrategy,
  setAuditCache, appendAuditCache, clearAuditCache,
} from './strategy_helpers'

export const useStrategyStore = defineStore('strategy', () => {
  // ---- State -----------------------------------------------------------
  /** @type {import('vue').Ref<Array<Object>>} */
  const strategies = ref([])
  /** @type {import('vue').Ref<Array<{code, name, category, description}>>} */
  const flagDefinitions = ref([])
  /** @type {import('vue').Ref<Record<number, Record<string, Array<Object>>>>}  按 (id, trdDate) 嵌套 */
  const auditCache = ref({})

  // ---- 运行时状态 -------------------------------------------------------
  const loading = ref(false)
  const error = ref(null)
  const lastUpdated = ref(0)
  const { pending, isPending, setPending } = createPendingTracker()

  // ---- Actions ----------------------------------------------------------
  /**
   * 拉取策略列表（可按 status / type 过滤）
   * @param {{status?: string, type?: string}} [opts]
   */
  async function loadStrategies(opts = {}) {
    loading.value = true
    error.value = null
    try {
      const list = await strategyApi.list(opts)
      strategies.value = Array.isArray(list) ? list : []
      lastUpdated.value = Date.now()
      return strategies.value
    } catch (e) {
      error.value = e?.message || 'loadStrategies failed'
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * 拉取单个策略 detail（含嵌套 regimes.grids），upsert 进缓存
   * @param {number} id
   */
  async function loadStrategy(id) {
    try {
      const strat = await strategyApi.getById(id)
      upsertStrategy(strategies.value, strat)
      return strat
    } catch (e) {
      error.value = e?.message || 'loadStrategy failed'
      throw e
    }
  }

  /**
   * 创建策略（payload 含嵌套 regimes + grids）；成功后追加进缓存
   * @param {Object} payload
   */
  async function createStrategy(payload) {
    const key = 'create'
    setPending(key, true)
    try {
      const strat = await strategyApi.create(payload)
      upsertStrategy(strategies.value, strat)
      return strat
    } finally {
      setPending(key, false)
    }
  }

  /**
   * 更新策略字段；成功后 in-place 替换
   * @param {number} id
   * @param {Object} patch
   */
  async function updateStrategy(id, patch) {
    const key = `update:${id}`
    setPending(key, true)
    try {
      const strat = await strategyApi.update(id, patch)
      upsertStrategy(strategies.value, strat)
      return strat
    } finally {
      setPending(key, false)
    }
  }

  /**
   * 级联删除策略（含 regimes/grids/audits）
   * @param {number} id
   */
  async function deleteStrategy(id) {
    const key = `delete:${id}`
    setPending(key, true)
    try {
      await strategyApi.delete(id)
      removeStrategy(strategies.value, id)
      clearAuditCache(auditCache.value, id)
    } finally {
      setPending(key, false)
    }
  }

  /**
   * 控制（pause / resume / stop / clear_now）；成功后更新本地 status
   * @param {number} id
   * @param {'pause'|'resume'|'stop'|'clear_now'} action
   */
  async function controlStrategy(id, action) {
    const key = `control:${id}:${action}`
    setPending(key, true)
    try {
      const res = await strategyApi.control(id, action)
      const local = strategies.value.find((s) => s.id === id)
      // res.status 是后端实际 status；clear_now 时可能不存在（按 id in-place 替换）
      if (local && res?.status) local.status = res.status
      return res
    } finally {
      setPending(key, false)
    }
  }

  /**
   * 加载 flag 注册表（前端下拉 / 多选源数据）
   */
  async function loadFlagDefinitions() {
    try {
      const res = await strategyApi.getFlagDefinitions()
      const list = res?.list ?? res
      flagDefinitions.value = Array.isArray(list) ? list : []
      return flagDefinitions.value
    } catch (e) {
      error.value = e?.message || 'loadFlagDefinitions failed'
      throw e
    }
  }

  /**
   * 加载指定日期的 audit 列表（按 (id, trdDate) 缓存）
   * @param {number} id
   * @param {string} trdDate 8 位 YYYYMMDD
   */
  async function loadAudit(id, trdDate) {
    try {
      const list = await strategyApi.getAudit(id, trdDate)
      const arr = Array.isArray(list) ? list : []
      setAuditCache(auditCache.value, id, trdDate, arr)
      return arr
    } catch (e) {
      error.value = e?.message || 'loadAudit failed'
      throw e
    }
  }

  /**
   * 追加单条 audit（task 12 增量推送用）
   * @param {number} id
   * @param {string} trdDate
   * @param {Object} audit
   */
  function appendAudit(id, trdDate, audit) {
    appendAuditCache(auditCache.value, id, trdDate, audit)
  }

  // ---- Getters ----------------------------------------------------------
  const activeStrategies = computed(() =>
    strategies.value.filter((s) => s.status === 'active')
  )
  const pausedStrategies = computed(() =>
    strategies.value.filter((s) => s.status === 'paused')
  )
  const stoppedStrategies = computed(() =>
    strategies.value.filter((s) => s.status === 'stopped')
  )
  const generalStrategies = computed(() =>
    strategies.value.filter((s) => s.type === 'general')
  )
  const t0Strategies = computed(() =>
    strategies.value.filter((s) => s.type === 't0')
  )

  function getById(id) {
    return strategies.value.find((s) => s.id === id)
  }
  function getAudit(id, trdDate) {
    return auditCache.value[id]?.[trdDate] || []
  }

  return {
    // state
    strategies, flagDefinitions, auditCache,
    loading, error, lastUpdated, pending,
    // actions
    loadStrategies, loadStrategy,
    createStrategy, updateStrategy, deleteStrategy,
    controlStrategy, loadFlagDefinitions, loadAudit, appendAudit,
    // getters（computed）
    activeStrategies, pausedStrategies, stoppedStrategies,
    generalStrategies, t0Strategies,
    getById, getAudit,
    // helpers
    _isPending: isPending,
  }
})
