import axios from 'axios'
import { ref } from 'vue'

const API_BASE = '/api'

// HTTP API
export const api = {
  // 持仓
  async getPositions() {
    const res = await axios.get(`${API_BASE}/positions`)
    return res.data
  },
  async initPosition(stockCode) {
    const res = await axios.post(`${API_BASE}/positions/${stockCode}/init`)
    return res.data
  },

  // 委托
  async getOrders(stockCode) {
    const params = stockCode ? { stock_code: stockCode } : {}
    const res = await axios.get(`${API_BASE}/orders`, { params })
    return res.data
  },
  async createOrder(orderData) {
    const res = await axios.post(`${API_BASE}/orders`, orderData)
    return res.data
  },
  async cancelOrder(orderId) {
    const res = await axios.delete(`${API_BASE}/orders/${orderId}`)
    return res.data
  },

  // 成交
  async getTrades(stockCode) {
    const params = stockCode ? { stock_code: stockCode } : {}
    const res = await axios.get(`${API_BASE}/trades`, { params })
    return res.data
  },

  // 资金
  async getAsset() {
    const res = await axios.get(`${API_BASE}/asset`)
    return res.data
  }
}

// WebSocket
export function createWSConnection(channel = 'order_update') {
  const wsUrl = `ws://${window.location.host}/ws/${channel}`
  const ws = ref(null)
  const messages = ref([])
  const connected = ref(false)

  function connect() {
    ws.value = new WebSocket(wsUrl)

    ws.value.onopen = () => {
      connected.value = true
      console.log(`[WS] Connected to ${channel}`)
    }

    ws.value.onmessage = (event) => {
      const data = JSON.parse(event.data)
      messages.value.push(data)
    }

    ws.value.onclose = () => {
      connected.value = false
      console.log(`[WS] Disconnected from ${channel}`)
    }

    ws.value.onerror = (error) => {
      console.error(`[WS] Error on ${channel}:`, error)
    }
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
    }
  }

  connect()

  return {
    ws,
    messages,
    connected,
    disconnect
  }
}