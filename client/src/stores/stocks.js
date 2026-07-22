import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { stocksApi } from '../api'

/**
 * 股票基础信息 store
 * v25 stocks-cache-and-short-name: 全量缓存 + 真分页 + autocomplete 筛选
 * v26 (2026-07-12-universalize-stockcode-autocomplete): 多页面共用 cache
 * v32 (2026-07-14-stock-names-from-cache): +stockName(code) getter,供表格/表单查名称
 *
 * 数据源：
 *   1. REST GET /api/stocks?page=N&page_size=100     循环拉全量 → cache (autocomplete 用)
 *   2. REST GET /api/stocks?page=N&page_size=20      单页拉 → pageRows (表格分页)
 *   3. REST PATCH /api/stocks/{code}                admin 编辑 + 同步 cache + pageRows
 *
 * 缓存策略 (v26):
 *   - cache: 全量 5529 内存缓存，刷新页面重拉 ~18s
 *   - cacheLoaded: bool，cache 是否加载完成
 *   - 多个页面 (Trade / T0Trade / StrategyTrade / AdminStockConfig) 共享同一 cache
 *     - App.vue onMounted 触发 loadCache()，进 Trade 页 0 等待
 *     - StockCodePicker.ensureCache() 在输入时也兜底触发（防 cache 失效）
 *     - loadCache() 内置 cacheLoading 防重入（v26 单例保证）
 *
 * 字段精简历史:
 *   v22 (2026-07-10) stock-info-editor: 11 字段编辑
 *   v23 (2026-07-12) slim-stocks-table: 5 字段编辑(白名单)
 *   v25 (2026-07-12) stocks-cache-and-short-name: +short_name, 6 字段编辑 + 全量缓存
 *   v26 (2026-07-12) universalize-stockcode-autocomplete: cache 跨页面共享 + autocomplete 通用化
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
   * 按 stock_code 查名称（v32 stock-names-from-cache）
   * 返回 null 表示查不到/缓存未加载；调用方决定占位字符串
   */
  function stockName(code) {
    if (!code) return null
    if (!cacheLoaded.value || !cache.value.length) return null
    const hit = cache.value.find((s) => s.stock_code === code)
    return hit?.stock_name || null
  }

  /**
   * v80: 按 stock_code 查价格小数位精度 (scale)
   * 返回 number (默认 2); cache miss 返回 2 兜底
   */
  function stockScale(code) {
    if (!code) return 2
    if (!cacheLoaded.value || !cache.value.length) return 2
    const hit = cache.value.find((s) => s.stock_code === code)
    const scale = hit?.scale
    if (scale === null || scale === undefined) return 2
    const n = Number(scale)
    if (!Number.isFinite(n) || n < 0 || n > 6) return 2  // 兜底 >6 → 2
    return Math.floor(n)
  }

  /**
   * v80: 按 stock_code 查证券类型 stktype (0=股票 1=ETF)
   * 返回 number (默认 0); cache miss 返回 0 兜底
   */
  function stockStktype(code) {
    if (!code) return 0
    if (!cacheLoaded.value || !cache.value.length) return 0
    const hit = cache.value.find((s) => s.stock_code === code)
    const t = hit?.stktype
    if (t === null || t === undefined) return 0
    return Number(t) || 0
  }

  // ==================== 添加 (v46 stock-info-create) ====================

  // 添加 loading（与 editLoading 同）
  const createLoading = ref(false)

  /**
   * admin 添加证券（REQ-STOCK-006 / REQ-FE-STOCK-CREATE）
   * 同时同步 cache + total + pageRows
   * @param {Object} payload 8 字段: stock_code(必填) + stock_name(必填) + 可选 sector/short_name/is_t0_able/min_buy_qty/trade_unit
   * @returns {Promise<{ok: boolean, msg?: string, data?: Object}>}
   */
  async function createStock(payload) {
    createLoading.value = true
    try {
      const data = await stocksApi.create(payload)
      // 同步 cache（unshift 头部，便于 autocomplete）
      cache.value.unshift(data)
      // total +1
      total.value += 1
      // 当前页立即显示（如果当前是第 1 页或 pageRows 空）
      if (page.value === 1) {
        pageRows.value.unshift(data)
      }
      return { ok: true, msg: '添加成功', data }
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || '添加失败'
      return { ok: false, msg }
    } finally {
      createLoading.value = false
    }
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
    createLoading,  // v46 stock-info-create
    // actions
    loadCache,
    searchCache,
    fetchPage,
    setPage,
    setPageSize,
    openEdit,
    closeEdit,
    saveEdit,
    createStock,  // v46 stock-info-create
    stockName,
    stockScale,    // v80: 价格小数位精度
    stockStktype,  // v80: 证券类型
  }
})