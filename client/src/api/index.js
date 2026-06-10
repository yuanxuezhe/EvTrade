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

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (onUnauthorized) onUnauthorized()
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
  // 持仓
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
    const res = await http.post('/orders', orderData)
    return res.data
  },
  async placeOrder(orderData) {
    const res = await http.post('/orders/place', orderData)
    return res.data
  },
  async cancelOrder(orderId) {
    const res = await http.delete(`/orders/${orderId}`)
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
