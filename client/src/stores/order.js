import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'
import { useHoldingsStore } from './holdings'

/**
 * 委托/成交 操作层
 *
 * v8: 单一缓存源架构
 *   - holdings store 是权威缓存（orders/trades ref + applyOrderPush/applyTradePush 守门）
 *   - orderStore 不再持有独立 orders/trades,只暴露 actions
 *   - 视图层读数据走 holdingsStore.orders / holdingsStore.trades
 *   - 下单后走 upsertLocal 转发到 holdings 缓存
 *
 * 关键设计：
 *   - createOrder 旧调用: 推数组进 orders → 破坏(类型错乱)
 *     现在: 调 api → 取 list[0] → upsertLocal(holdings.applyOrderPush) → 写流水
 *   - placeOrder 跟 createOrder 等价（v8 统一 list[0] 模式）
 *   - cancelOrder: 乐观更新 holdings.orders[i].status = '51' (待撤), 等 push 改终态
 */
export const useOrderStore = defineStore('order', () => {
  // 不再持有独立 orders/trades, 全部走 holdings store
  // 保留 loading 状态供 Trade.vue 按钮禁用
  const placing = ref(false)
  const cancelling = ref(false)

  /**
   * v8: 下单后立即写缓存（关键: 推送匹配需要 order_no 在缓存里）
   *   走 holdings.applyOrderPush → 单点守门 + 单点 upsert 逻辑
   */
  function _upsertToHoldings(order) {
    if (!order || !order.order_no) return
    const holdings = useHoldingsStore()
    // applyOrderPush 已含激活日守门 + 防御性 status 重算
    holdings.applyOrderPush(order, 'open')
  }

  async function createOrder(orderData) {
    placing.value = true
    try {
      // api.createOrder 已被拦截器解包 → res.data = list 数组
      const list = await api.createOrder(orderData)
      const order = (Array.isArray(list) && list[0]) || null
      if (order) {
        _upsertToHoldings(order)
      }
      return order
    } finally {
      placing.value = false
    }
  }

  async function placeOrder(orderData) {
    // v8: placeOrder 跟 createOrder 等价(后端同一接口, 现在统一返 list[0])
    return await createOrder(orderData)
  }

  async function cancelOrder(orderNo, trdDate) {
    cancelling.value = true
    try {
      // v6: 撤单用 order_no + trd_date；status 由 ord_cfm push 异步改, 不本地写
      await api.cancelOrder(orderNo, trdDate)
      // 乐观更新 UI: 标记为"待撤" (51), 等 push 改终态
      const holdings = useHoldingsStore()
      const order = holdings.orders.find(o => o.order_no === orderNo)
      if (order && !['51', '52', '53', '54', '55', '56'].includes(String(order.status))) {
        order.status = '51'
      }
    } finally {
      cancelling.value = false
    }
  }

  return {
    // state
    placing, cancelling,
    // actions
    createOrder, placeOrder, cancelOrder
    // v8: 不暴露 orders/trades getter, view 必须显式 useHoldingsStore().orders
    //     避免"看起来是 orderStore 独立缓存"误解, 强制走单一源
  }
})
