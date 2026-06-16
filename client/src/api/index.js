import axios from 'axios'

const API_BASE = '/api'
const TOKEN_KEY = 'evtrade-token'

// ============================================================
// Axios 实例 + 拦截器
// ============================================================
export const http = axios.create({
  baseURL: API_BASE,
  timeout: 15000
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 全局回调：401 时由路由层处理
let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

// 后端 RPC 响应统一为 {code, msg, list}：
//   - code === 0：把 res.data 替换为 list，调用方拿到的就是数组
//   - code !== 0：红色 ElMessage.error(msg) 并 reject，调用方 await 抛错
// 异步加载 element-plus 以避免与 main.js 的初始化循环依赖。
function _isRpcResponse(body) {
  return (
    body &&
    typeof body === 'object' &&
    !Array.isArray(body) &&
    'code' in body &&
    'msg' in body &&
    ('list' in body || 'data' in body)
  )
}

async function _showRpcError(msg) {
  try {
    const { ElMessage } = await import('element-plus')
    ElMessage.error(msg || '请求失败')
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('[api] failed to show ElMessage:', e)
  }
}

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (_isRpcResponse(body)) {
      const code = Number(body.code)
      if (code !== 0) {
        _showRpcError(body.msg)
        return Promise.reject({ rpc: true, code, msg: body.msg })
      }
      // 解包：统一返回 list 数组；兼容旧 data 字段
      if (Array.isArray(body.list)) {
        res.data = body.list
      } else if (body.data != null) {
        res.data = body.data
      } else {
        res.data = body
      }
    }
    return res
  },
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (onUnauthorized) onUnauthorized()
    }
    // 屏障/拒绝类 (403/422/500/503): FastAPI HTTPException 走 detail
    // 提取 detail.code + detail.msg 弹 ElMessage, 不然前端只看到 console 裸 503
    if (status && status >= 400) {
      const detail = err.response?.data?.detail
      let msg = null
      if (typeof detail === 'string') {
        msg = detail
      } else if (detail && typeof detail === 'object') {
        msg = detail.msg || detail.code || null
      }
      if (msg) {
        _showRpcError(msg)
      } else if (status === 503) {
        // 兜底：503 业务没返 detail 时也给个提示
        _showRpcError('服务暂不可用 (503)，请稍后重试')
      }
    }
    return Promise.reject(err)
  }
)

// ============================================================
// Token 管理
// ============================================================
export const tokenStorage = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY)
}

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
  async getOrders(stockCode) {
    const params = stockCode ? { stock_code: stockCode } : {}
    const res = await http.get('/orders', { params })
    return res.data
  },
  async createOrder(orderData) {
    const res = await http.post('/orders/place', orderData)
    return res.data
  },
  async placeOrder(orderData) {
    const res = await http.post('/orders/place', orderData)
    return res.data
  },
  async cancelOrder(orderNo, trdDate) {
    // v6: 撤单 URL = DELETE /api/orders/{order_no}?trd_date=YYYYMMDD
    const res = await http.delete(`/orders/${orderNo}`, { params: { trd_date: trdDate } })
    return res.data
  },

  // 成交
  async getTrades(stockCode) {
    const params = stockCode ? { stock_code: stockCode } : {}
    const res = await http.get('/trades', { params })
    return res.data
  },

  // 资金
  async getAsset() {
    const res = await http.get('/asset')
    return res.data
  },

  // 交易时段（公开接口）
  async getTradingClock() {
    const res = await http.get('/trading/clock')
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
  async changePassword(oldPassword, newPassword) {
    const res = await http.post('/auth/change-password', {
      old_password: oldPassword,
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
