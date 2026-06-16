import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'

export const useOrderStore = defineStore('order', () => {
  const orders = ref([])
  const trades = ref([])

  async function fetchOrders(stockCode) {
    orders.value = await api.getOrders(stockCode)
  }

  async function fetchTrades(stockCode) {
    trades.value = await api.getTrades(stockCode)
  }

  async function createOrder(orderData) {
    const order = await api.createOrder(orderData)
    orders.value.push(order)
    return order
  }

  async function placeOrder(orderData) {
    const list = await api.placeOrder(orderData)
    return (Array.isArray(list) && list[0]) || null
  }

  async function cancelOrder(orderNo, trdDate) {
    // v6: 撤单用 order_no + trd_date；status 由 ord_cfm push 异步改, 不本地写
    await api.cancelOrder(orderNo, trdDate)
    // 乐观更新 UI: 标记为"已报待撤" (51), 等 push 改终态
    const order = orders.value.find(o => o.order_no === orderNo)
    if (order && !['51', '52', '53', '54', '55', '56'].includes(String(order.status))) {
      order.status = '51'
    }
  }

  return {
    orders,
    trades,
    fetchOrders,
    fetchTrades,
    createOrder,
    placeOrder,
    cancelOrder
  }
})