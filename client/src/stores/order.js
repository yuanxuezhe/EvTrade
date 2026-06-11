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

  async function cancelOrder(orderId) {
    await api.cancelOrder(orderId)
    const order = orders.value.find(o => o.order_id === orderId)
    if (order) {
      // 柜台数字 54 = 已撤
      order.status = '54'
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