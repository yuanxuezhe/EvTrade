import { http, tokenStorage, setUnauthorizedHandler } from './http'

// ============================================================
// 业务 API
// ============================================================
export const api = {
  // 持仓（持仓查询 = 6 字段原始 RPC；持仓管理 = 含派生字段）
  async getHoldings() {
    const res = await http.get('/holdings')
    return res.data
  },
  async getPositions() {
    const res = await http.get('/positions')
    return res.data
  },
  async initPosition(stockCode) {
    const res = await http.post(`/positions/${stockCode}/init`)
    return res.data
  },

  // 委托
  // opts: undefined | string (stockCode) | { stockCode?, startDate?, endDate?, all?, limit? }
  // all=true 时前端 startup 缓存拉全量; taskId 过滤由前端缓存处理, 不走 API
  // 后向兼容: 无参 / 旧 string 调用 仍工作
  async getOrders(opts) {
    const params = {}
    if (typeof opts === 'string') {
      params.stock_code = opts
    } else if (opts && typeof opts === 'object') {
      if (opts.stockCode) params.stock_code = opts.stockCode
      if (opts.startDate) params.start_date = opts.startDate
      if (opts.endDate) params.end_date = opts.endDate
      if (opts.all) params.all = true  // 拉全量 (前端启动一次性缓存)
      if (opts.limit) params.limit = opts.limit
    }
    const res = await http.get('/orders', { params })
    return res.data
  },
  async createOrder(orderData) {
    // 后端返 {code, msg, order, list, broker_order_id, fee_breakdown, t0_adjusted_volume}
    //     拦截器解包后 res.data = list 数组
    //     调用方应取 res.data[0] 当 OrderOut(或保留 res.order 兼容旧代码)
    const res = await http.post('/orders/place', orderData)
    return res.data
  },
  async placeOrder(orderData) {
    // 跟 createOrder 同接口,返 list[0] = OrderOut
    //     orderStore.upsertLocal(res.data[0]) 立即写缓存
    const res = await http.post('/orders/place', orderData)
    return res.data
  },
  async cancelOrder(orderNo, trdDate) {
    // 撤单 URL = DELETE /api/orders/{order_no}?trd_date=YYYYMMDD
    const res = await http.delete(`/orders/${orderNo}`, { params: { trd_date: trdDate } })
    return res.data
  },

  // 成交
  // opts: undefined | string (stockCode) | { stockCode?, startDate?, endDate? }
  // 向后兼容: 无参 (bootstrap 当前用法) / 旧 string 调用 仍工作
  async getTrades(opts) {
    const params = {}
    if (typeof opts === 'string') {
      params.stock_code = opts
    } else if (opts && typeof opts === 'object') {
      if (opts.stockCode) params.stock_code = opts.stockCode
      if (opts.startDate) params.start_date = opts.startDate
      if (opts.endDate) params.end_date = opts.endDate
      if (opts.all) params.all = true
      if (opts.limit) params.limit = opts.limit
    }
    const res = await http.get('/trades', { params })
    return res.data
  },

  // 资金
  async getAsset() {
    const res = await http.get('/asset')
    return res.data
  },

  // RPC 三态健康状态 (来自 server/services/rpc_health 心跳)
  // AppHeader 右上角图标首屏用此接口初始化, 之后由 ws 推送 rpc_status 覆盖
  async getRpcStatus() {
    const res = await http.get('/asset/rpc-status')
    return res.data
  },

  // 交易时段（公开接口）
  async getTradingClock() {
    const res = await http.get('/trading/clock')
    return res.data
  },

  // 系统级查询（激活交易日权威源）
  //   - 返 {code, msg, list: [{trd_date, status: 'active'|'inactive'}]}
  //   - 拦截器解包后 res.data = list 数组
  //   - holdings.bootstrap() 调, 取 list[0]?.trd_date
  async getActiveDay() {
    const res = await http.get('/system/active-day')
    return res.data
  },

  // admin-only 调平 API（PUT, admin 鉴权在端点层 require_admin）
  //   输入 camelCase (deltaVol / deltaAvlVol / deltaCash / deltaTotalAsset)
  //   输出 snake_case (delta_vol / delta_avl_vol / delta_cash / delta_total_asset)
  //   reason 仅入 log, 不入库
  async adjustPosition(stockCode, { deltaVol, deltaAvlVol, reason } = {}) {
    const body = {}
    if (deltaVol !== undefined) body.delta_vol = deltaVol
    if (deltaAvlVol !== undefined) body.delta_avl_vol = deltaAvlVol
    if (reason !== undefined) body.reason = reason
    const res = await http.put(`/positions/${stockCode}/adjust`, body)
    return res.data
  },
  async adjustAsset({ deltaCash, deltaTotalAsset, reason } = {}) {
    const body = {}
    if (deltaCash !== undefined) body.delta_cash = deltaCash
    if (deltaTotalAsset !== undefined) body.delta_total_asset = deltaTotalAsset
    if (reason !== undefined) body.reason = reason
    const res = await http.put('/asset/adjust', body)
    return res.data
  }
}

// ============================================================
// 鉴权 API
// ============================================================
export const authApi = {
  async login(username, password) {
    // OAuth2PasswordRequestForm 要求 x-www-form-urlencoded
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    const res = await http.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })
    return res.data
  },
  async me() {
    const res = await http.get('/auth/me')
    return res.data
  },
  async updateProfile(payload) {
    const res = await http.patch('/auth/me', payload)
    return res.data
  },
  async changePassword(_oldPassword, newPassword) {
    // v_next: 后端不校验旧密码、不限制长度 — 前端只发新密码
    const res = await http.post('/auth/change-password', {
      new_password: newPassword
    })
    return res.data
  },
  async logout() {
    try {
      await http.post('/auth/logout')
    } catch {
      // ignore
    }
  }
}

// ============================================================
// 股票基础信息 API (change stock-info-crawler 查询 + change stock-info-editor 编辑)
// ============================================================
export { stocksApi } from './stocks'

// ============================================================
// 用户管理 API（admin）
// ============================================================
export const userApi = {
  async list(params = {}) {
    const res = await http.get('/users', { params })
    return res.data
  },
  async create(payload) {
    const res = await http.post('/users', payload)
    return res.data
  },
  async update(id, payload) {
    const res = await http.patch(`/users/${id}`, payload)
    return res.data
  },
  async resetPassword(id, newPassword) {
    const res = await http.post(`/users/${id}/reset-password`, { new_password: newPassword })
    return res.data
  },
  async delete(id) {
    const res = await http.delete(`/users/${id}`)
    return res.data
  }
}

// ============================================================
// 脚本策略 API (script-strategy change): 前端编写 Python 脚本 + 回测 + 实盘
// ============================================================
export { scriptStrategyApi } from './script_strategy'

// ============================================================
// WebSocket（保留）
// ============================================================
export function createWSConnection(channel = 'order_update') {
  const wsUrl = `ws://${window.location.host}/ws/${channel}`
  const ws = { value: null }
  const messages = []
  let connected = false

  function connect() {
    ws.value = new WebSocket(wsUrl)
    ws.value.onopen = () => { connected = true }
    ws.value.onmessage = (e) => { messages.push(JSON.parse(e.data)) }
    ws.value.onclose = () => { connected = false }
  }

  function disconnect() {
    if (ws.value) ws.value.close()
  }

  connect()
  return { ws, messages, connected, disconnect }
}
