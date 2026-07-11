import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { stocksApi } from '../api'

/**
 * 股票基础信息 store (v22 stock-info-editor)
 *
 * 数据源：
 *   1. REST GET /api/stocks              列表缓存
 *   2. REST GET /api/stocks/{code}       详情(弹窗编辑时拉)
 *   3. REST PATCH /api/stocks/{code}     admin 编辑
 *
 * 与 sync store 的区别：stocks 数据来自爬虫入仓的快照,
 * admin 编辑后只更新本地缓存对应行,不触发任何 WS push（v22 范围最小化）。
 */
export const useStocksStore = defineStore('stocks', () => {
  // 列表（按 stock_code 排序）
  const list = ref([])
  // 加载态
  const loading = ref(false)
  // 当前编辑中的 stock_code
  const editingCode = ref(null)
  // 详情编辑表单（dialog 用）
  const editForm = reactive({})
  // 编辑 loading
  const editLoading = ref(false)

  /**
   * 拉列表（覆盖本地缓存）
   * @param {Object} params { industry?, market?, limit? }
   */
  async function fetchList(params = {}) {
    loading.value = true
    try {
      list.value = await stocksApi.list(params)
    } finally {
      loading.value = false
    }
    return list.value
  }

  /**
   * 拉详情填到 editForm（打开 dialog 时）
   * @returns {Promise<boolean>} 成功 true / 失败 false
   */
  async function openEdit(stockCode) {
    editingCode.value = stockCode
    const data = await stocksApi.getOne(stockCode)
    if (!data) return false
    // 重置 editForm
    Object.keys(editForm).forEach((k) => delete editForm[k])
    Object.assign(editForm, {
      stock_name: data.stock_name || '',
      industry: data.industry || '',
      sector: data.sector || '',
      market: data.market || '',
      list_date: data.list_date || '',
      total_share: data.total_share ?? 0,
      float_share: data.float_share ?? 0,
      market_cap: data.market_cap ?? 0,
      pe_ratio: data.pe_ratio ?? null,
      pb_ratio: data.pb_ratio ?? null,
      intro: data.intro || ''
    })
    return true
  }

  function closeEdit() {
    editingCode.value = null
    Object.keys(editForm).forEach((k) => delete editForm[k])
  }

  /**
   * 保存编辑（PATCH）
   * @returns {Promise<{ok: boolean, msg?: string}>}
   */
  async function saveEdit() {
    if (!editingCode.value) {
      return { ok: false, msg: '未选中股票' }
    }
    editLoading.value = true
    try {
      // 只发有改动的字段 — 后端按 exclude_none 处理
      const payload = {}
      for (const [k, v] of Object.entries(editForm)) {
        // 数字字段：null 表示未填,跳过
        if (v === '' || v === null || v === undefined) continue
        payload[k] = v
      }
      if (Object.keys(payload).length === 0) {
        return { ok: false, msg: '没有修改任何字段' }
      }
      const updated = await stocksApi.update(editingCode.value, payload)
      // 同步本地缓存列表对应行
      const idx = list.value.findIndex((s) => s.stock_code === editingCode.value)
      if (idx >= 0) list.value.splice(idx, 1, updated)
      return { ok: true, msg: '保存成功', data: updated }
    } catch (e) {
      const msg =
        e?.response?.data?.detail || e?.message || '保存失败'
      return { ok: false, msg }
    } finally {
      editLoading.value = false
    }
  }

  return {
    list,
    loading,
    editingCode,
    editForm,
    editLoading,
    fetchList,
    openEdit,
    closeEdit,
    saveEdit
  }
})