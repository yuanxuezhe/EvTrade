import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { stocksApi } from '../api'

/**
 * 股票基础信息 store
 * v25 stocks-cache-and-short-name: 全量缓存 + 真分页 + autocomplete 筛选
 *
 * 数据源：
 *   1. REST GET /api/stocks?page=N&page_size=100     循环拉全量 → cache (admin autocomplete 用)
 *   2. REST GET /api/stocks?page=N&page_size=20      单页拉 → pageRows (表格分页)
 *   3. REST PATCH /api/stocks/{code}                admin 编辑 + 同步 cache + pageRows
 *
 * 缓存策略:
 *   - cache: 全量 5529 内存缓存，刷新页面重拉 ~18s
 *   - pageRows: 当前页（后端分页）
 *   - total: 后端总数，用于 el-pagination
 *   - cacheLoaded: bool，cache 是否加载完成（autocomplete 用）
 *
 * 字段精简历史:
 *   v22 (2026-07-10) stock-info-editor: 11 字段编辑
 *   v23 (2026-07-12) slim-stocks-table: 5 字段编辑(白名单)
 *   v25 (2026-07-12) stocks-cache-and-short-name: +short_name, 6 字段编辑 + 全量缓存
 */
export const useStocksStore = defineStore('stocks', () => {
  // ==================== 状态 ====================
  // 全量缓存（autocomplete 用）
  const cache = ref([])
  const cacheLoading = ref(false)
  const cacheLoaded = ref(false)
  const cacheProgress = ref(0)  // 0..1, 加载进度
  const cacheError = ref(null)

  // 表格分页（后端分页）
  const pageRows = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)  // page fetch loading

  // 当前编辑中的 stock_code
  const editingCode = ref(null)
  // 详情编辑表单（dialog 用）
  const editForm = reactive({})
  // 编辑 loading
  const editLoading = ref(false)

  // ==================== cache 加载 ====================

  /**
   * 全量加载 cache（循环分页拉）
   * 一次 page_size=100,直到 total === cache.length
   * 调用方负责 catch cacheError
   */
  async function loadCache({ page_size = 100 } = {}) {
    if (cacheLoading.value) return
    cacheLoading.value = true
    cacheError.value = null
    cacheProgress.value = 0
    try {
      let all = []
      let p = 1
      const MAX_PAGES = 200  // 安全上限: 200 * 100 = 20000 行
      while (p <= MAX_PAGES) {
        const res = await stocksApi.list({ page: p, page_size })
        all = all.concat(res.list)
        cacheProgress.value = res.total > 0 ? Math.min(all.length / res.total, 1) : 1
        if (all.length >= res.total || res.list.length === 0) break
        p += 1
      }
      cache.value = all
      cacheLoaded.value = true
    } catch (e) {
      cacheError.value = e?.message || 'cache 加载失败'
      throw e
    } finally {
      cacheLoading.value = false
    }
  }

  /**
   * cache 内搜索（autocomplete 用）
   * 三路 OR: stock_code 前缀 OR stock_name 包含 OR short_name 前缀
   * @param {string} query
   * @param {number} limit
   * @returns {Array} 候选 stock 列表
   */
  function searchCache(query, limit = 50) {
    if (!query || !cache.value.length) return []
    const q = query.trim().toLowerCase()
    if (!q) return []
    const matches = []
    for (const s of cache.value) {
      const code = (s.stock_code || '').toLowerCase()
      const name = (s.stock_name || '').toLowerCase()
      const short = (s.short_name || '').toLowerCase()
      let score = 0
      if (code.startsWith(q)) score = 3          // 代码前缀优先
      else if (short.startsWith(q)) score = 2    // 拼音次之
      else if (name.includes(q)) score = 1       // 名称包含兜底
      if (score > 0) matches.push({ s, score })
    }
    matches.sort((a, b) => b.score - a.score)
    return matches.slice(0, limit).map((m) => m.s)
  }

  // ==================== 表格分页 ====================

  /**
   * 拉当前页（后端分页）
   * @param {Object} params { sector?, keyword?, is_t0_able? } (page/pageSize 走 store 状态)
   */
  async function fetchPage(extraParams = {}) {
    loading.value = true
    try {
      const res = await stocksApi.list({
        page: page.value,
        page_size: pageSize.value,
        ...extraParams
      })
      pageRows.value = res.list
      total.value = res.total
    } finally {
      loading.value = false
    }
    return pageRows.value
  }

  /**
   * 设置页码并拉取
   */
  async function setPage(p) {
    page.value = p
    await fetchPage()
  }

  /**
   * 设置每页大小并回到第 1 页
   */
  async function setPageSize(sz) {
    pageSize.value = sz
    page.value = 1
    await fetchPage()
  }

  // ==================== 编辑 ====================

  /**
   * 拉详情填到 editForm（打开 dialog 时）
   * @returns {Promise<boolean>} 成功 true / 失败 false
   */
  async function openEdit(stockCode) {
    editingCode.value = stockCode
    const data = await stocksApi.getOne(stockCode)
    if (!data) return false
    Object.keys(editForm).forEach((k) => delete editForm[k])
    Object.assign(editForm, {
      stock_name: data.stock_name || '',
      sector: data.sector || '',
      is_t0_able: data.is_t0_able ?? false,
      min_buy_qty: data.min_buy_qty ?? 100,
      trade_unit: data.trade_unit ?? 1,
      short_name: data.short_name || ''
    })
    return true
  }

  function closeEdit() {
    editingCode.value = null
    Object.keys(editForm).forEach((k) => delete editForm[k])
  }

  /**
   * 保存编辑（PATCH）
   * 同时刷新 cache + pageRows + 后端
   * @returns {Promise<{ok: boolean, msg?: string}>}
   */
  async function saveEdit() {
    if (!editingCode.value) {
      return { ok: false, msg: '未选中股票' }
    }
    editLoading.value = true
    try {
      const payload = {}
      for (const [k, v] of Object.entries(editForm)) {
        if (v === '' || v === null || v === undefined) continue
        payload[k] = v
      }
      if (Object.keys(payload).length === 0) {
        return { ok: false, msg: '没有修改任何字段' }
      }
      const updated = await stocksApi.update(editingCode.value, payload)

      // 1. 同步更新 cache（按 stock_code 查找）
      const cIdx = cache.value.findIndex((s) => s.stock_code === editingCode.value)
      if (cIdx >= 0) cache.value.splice(cIdx, 1, updated)

      // 2. 同步更新 pageRows（如果在当前页）
      const pIdx = pageRows.value.findIndex((s) => s.stock_code === editingCode.value)
      if (pIdx >= 0) pageRows.value.splice(pIdx, 1, updated)

      return { ok: true, msg: '保存成功', data: updated }
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || '保存失败'
      return { ok: false, msg }
    } finally {
      editLoading.value = false
    }
  }

  return {
    // state
    cache,
    cacheLoading,
    cacheLoaded,
    cacheProgress,
    cacheError,
    pageRows,
    total,
    page,
    pageSize,
    loading,
    editingCode,
    editForm,
    editLoading,
    // actions
    loadCache,
    searchCache,
    fetchPage,
    setPage,
    setPageSize,
    openEdit,
    closeEdit,
    saveEdit
  }
})