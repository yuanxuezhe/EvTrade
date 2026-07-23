import { defineStore } from 'pinia'
import { reactive, ref, computed } from 'vue'
import { stocksApi } from '../api'
import { openDB, idbGet, idbPut } from '../utils/idb'

/**
 * 股票基础信息 store (v90 IndexedDB + Map 重构)
 *
 * v90 核心改造:
 *   - cache: ref([]) -> cacheMap: reactive(new Map())  O(1) 查找
 *   - loadCache() 串行 56 次分页 -> initCache() + refreshCache() 1 次 /stocks/all
 *   - 启动顺序: loadFromIDB() 秒载 Map -> 后台 refreshCache() 静默更新
 *   - 持久化: 全量数组写 IDB 单 key, 刷新页面 F5 秒开
 *   - CRUD 同步: saveEdit/createStock 成功后 upsertLocal() 同步 Map + IDB
 *
 * 数据源:
 *   1. IDB 'EvTrade-stocks/kv[all]'             启动秒载 (F5 不再拉后端)
 *   2. REST GET /api/stocks/all                  全量刷新 (首次 / 手动同步)
 *   3. REST GET /api/stocks?page=N&page_size=20  单页拉 -> pageRows (表格分页)
 *   4. REST PATCH /api/stocks/{code}             admin 编辑 + upsertLocal
 *   5. REST POST /api/stocks                     admin 添加 + upsertLocal
 *
 * 兼容字段 (外部模板依赖):
 *   - cache:        computed, 返 Array.from(cacheMap.values()) (StockCodePicker/AdminStockConfig 用 .length)
 *   - cacheLoaded / cacheLoading / cacheProgress: 保留同名 ref
 *   - stockName(code) / stockScale(code) / stockStktype(code): 签名不变, 内部改 Map.get
 */
const IDB_DB_NAME = 'stocks'
const IDB_STORE = 'kv'
const IDB_KEY = 'all'  // 单 key 存全量数组, 启动一次 get

export const useStocksStore = defineStore('stocks', () => {
  // ==================== 状态 ====================
  // 内存 Map (O(1) 查找, reactive 触发重渲染)
  const cacheMap = reactive(new Map())  // code -> stock dict
  const cacheLoading = ref(false)
  const cacheLoaded = ref(false)
  const cacheProgress = ref(0)  // 0..1, 加载进度
  const cacheError = ref(null)

  // 兼容: cache 作为 computed 返回数组 (模板里用 store.cache.length / v-for)
  const cache = computed(() => Array.from(cacheMap.values()))

  // 表格分页 (后端分页)
  const pageRows = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)

  // 当前编辑中的 stock_code
  const editingCode = ref(null)
  // 详情编辑表单 (dialog 用)
  const editForm = reactive({})
  // 编辑 loading
  const editLoading = ref(false)

  // ==================== IDB 持久化 ====================

  /**
   * 启动时从 IDB 加载到 Map (秒开, F5 不再拉后端)
   * IDB 空 (首次/清缓存) -> cacheLoaded 保持 false, 由调用方触发 refreshCache
   */
  async function loadFromIDB() {
    try {
      const db = await openDB(IDB_DB_NAME, 1, [IDB_STORE])
      const arr = await idbGet(db, IDB_STORE, IDB_KEY)
      if (Array.isArray(arr) && arr.length > 0) {
        cacheMap.clear()
        for (const s of arr) {
          if (s && s.stock_code) cacheMap.set(s.stock_code, s)
        }
        cacheLoaded.value = true
        cacheProgress.value = 1
      }
    } catch (e) {
      // IDB 不可用 (Node 测试 / 隐私模式) -> 静默降级, 走 refreshCache
      console.warn('[stocks] loadFromIDB failed:', e?.message || e)
    }
  }

  /**
   * 把当前 cacheMap 全量写回 IDB (单 key, 覆盖)
   * 内部防抖: 多次 upsertLocal 短时间内只写 1 次
   */
  let _persistTimer = null
  function _persistIDB() {
    if (_persistTimer) return
    _persistTimer = setTimeout(async () => {
      _persistTimer = null
      try {
        const db = await openDB(IDB_DB_NAME, 1, [IDB_STORE])
        const arr = Array.from(cacheMap.values())
        await idbPut(db, IDB_STORE, IDB_KEY, arr)
      } catch (e) {
        console.warn('[stocks] persistIDB failed:', e?.message || e)
      }
    }, 300)
  }

  // ==================== cache 加载 ====================

  /**
   * 全量拉取并落 IDB (首次 / 手动刷新用)
   * 调 GET /api/stocks/all 1 次拿全 5529 条, 覆盖 Map + IDB
   */
  async function refreshCache() {
    if (cacheLoading.value) return
    cacheLoading.value = true
    cacheError.value = null
    cacheProgress.value = 0
    try {
      const res = await stocksApi.listAll()
      cacheMap.clear()
      for (const s of res.list) {
        if (s && s.stock_code) cacheMap.set(s.stock_code, s)
      }
      cacheLoaded.value = true
      cacheProgress.value = 1
      // 写 IDB (异步, 不阻塞)
      try {
        const db = await openDB(IDB_DB_NAME, 1, [IDB_STORE])
        await idbPut(db, IDB_STORE, IDB_KEY, res.list)
      } catch (e) {
        console.warn('[stocks] IDB put failed:', e?.message || e)
      }
    } catch (e) {
      cacheError.value = e?.message || 'cache 加载失败'
      throw e
    } finally {
      cacheLoading.value = false
    }
  }

  /**
   * 启动入口: 先 IDB 秒载, IDB 空则首次拉; 否则后台静默 refresh
   * App.vue onMounted / StockCodePicker.ensureCache 调这个
   */
  let _initPromise = null
  async function initCache() {
    if (_initPromise) return _initPromise
    _initPromise = (async () => {
      await loadFromIDB()
      if (!cacheLoaded.value) {
        // IDB 空 - 首次直接拉 (阻塞, 让调用方拿到数据)
        await refreshCache().catch((e) => {
          console.warn('[stocks] initCache refresh failed:', e?.message || e)
        })
      } else {
        // IDB 命中 - 后台静默刷新 (不阻塞)
        refreshCache().catch((e) => {
          console.warn('[stocks] initCache background refresh failed:', e?.message || e)
        })
      }
    })()
    return _initPromise
  }

  /**
   * cache 内搜索 (autocomplete 用)
   * 三路 OR: stock_code 前缀 OR stock_name 包含 OR short_name 前缀
   * @param {string} query
   * @param {number} limit
   * @returns {Array} 候选 stock 列表
   */
  function searchCache(query, limit = 50) {
    if (!query) return []
    const q = query.trim().toLowerCase()
    if (!q) return []
    const matches = []
    for (const s of cacheMap.values()) {
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
   * 拉当前页 (后端分页)
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

  function setPage(p) {
    page.value = p
    return fetchPage()
  }

  function setPageSize(sz) {
    pageSize.value = sz
    page.value = 1
    return fetchPage()
  }

  // ==================== 编辑 ====================

  /**
   * 拉详情填到 editForm (打开 dialog 时)
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
   * 按 stock_code 查名称 (v90 改 Map.get, O(1))
   * 返回 null 表示查不到/缓存未加载; 调用方决定占位字符串
   */
  function stockName(code) {
    if (!code) return null
    if (!cacheLoaded.value) return null
    return cacheMap.get(code)?.stock_name || null
  }

  /**
   * v80: 按 stock_code 查价格小数位精度 (scale)
   * 返回 number (默认 2); cache miss 返回 2 兜底
   */
  function stockScale(code) {
    if (!code) return 2
    if (!cacheLoaded.value) return 2
    const scale = cacheMap.get(code)?.scale
    if (scale === null || scale === undefined) return 2
    const n = Number(scale)
    if (!Number.isFinite(n) || n < 0 || n > 6) return 2  // 兜底 >6 -> 2
    return Math.floor(n)
  }

  /**
   * v80: 按 stock_code 查证券类型 stktype (0=股票 1=ETF)
   * 返回 number (默认 0); cache miss 返回 0 兜底
   */
  function stockStktype(code) {
    if (!code) return 0
    if (!cacheLoaded.value) return 0
    const t = cacheMap.get(code)?.stktype
    if (t === null || t === undefined) return 0
    return Number(t) || 0
  }

  // ==================== 添加 (v46 stock-info-create) ====================

  const createLoading = ref(false)

  /**
   * 本地 Map + IDB 同步 upsert (CRUD 成功后调用)
   * @param {Object} stock 完整 stock dict (含 stock_code)
   */
  function upsertLocal(stock) {
    if (!stock || !stock.stock_code) return
    cacheMap.set(stock.stock_code, stock)
    _persistIDB()
  }

  /**
   * admin 添加证券 (REQ-STOCK-006 / REQ-FE-STOCK-CREATE)
   * 同步 cache (Map + IDB) + total + pageRows
   * @param {Object} payload 6 字段: stock_code(必填) + stock_name(必填) + 可选 sector/is_t0_able/min_buy_qty/trade_unit
   * @returns {Promise<{ok: boolean, msg?: string, data?: Object}>}
   */
  async function createStock(payload) {
    createLoading.value = true
    try {
      const data = await stocksApi.create(payload)
      // 同步 Map + IDB
      upsertLocal(data)
      // total +1
      total.value += 1
      // 当前页立即显示 (如果当前是第 1 页或 pageRows 空)
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
   * 保存编辑 (PATCH)
   * 同步 Map + IDB + pageRows + 后端
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

      // 1. 同步 Map + IDB
      upsertLocal(updated)

      // 2. 同步 pageRows (如果在当前页)
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
    cache,            // v90: computed -> Array.from(cacheMap.values())
    cacheMap,         // v90: 新增, O(1) 查找
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
    createLoading,
    // actions
    initCache,        // v90: 替代 loadCache
    refreshCache,     // v90: 新增, 手动同步缓存
    loadFromIDB,      // v90: 新增, 启动秒载
    searchCache,
    fetchPage,
    setPage,
    setPageSize,
    openEdit,
    closeEdit,
    saveEdit,
    createStock,
    upsertLocal,      // v90: 新增, CRUD 后同步 Map + IDB
    stockName,
    stockScale,
    stockStktype,
  }
})
