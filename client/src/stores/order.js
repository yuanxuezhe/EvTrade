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
    const order = await api.placeOrder(orderData)
    return order
  }

  async function cancelOrder(orderId) {
    await api.cancelOrder(orderId)
    const order = orders.value.find(o => o.order_id === orderId)
    if (order) {
      order.status = 'cancelled'
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