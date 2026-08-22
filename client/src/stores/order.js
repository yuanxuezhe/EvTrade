import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../api'
import { sysconfigApi } from '../api/sysconfig'
import { useHoldingsStore } from './holdings'

/**
 * 委托/成交 操作层
 *
 * 单一缓存源架构
 *   - holdings store 是权威缓存（orders/trades ref + applyOrderPush/applyTradePush 守门）
 *   - orderStore 不再持有独立 orders/trades,只暴露 actions
 *   - 视图层读数据走 holdingsStore.orders / holdingsStore.trades
 *   - 下单后走 upsertLocal 转发到 holdings 缓存
 *
 * 关键设计：
 *   - createOrder 旧调用: 推数组进 orders → 破坏(类型错乱)
 *     现在: 调 api → 取 list[0] → upsertLocal(holdings.applyOrderPush) → 写流水
 *   - placeOrder 跟 createOrder 等价（统一 list[0] 模式）
 *   - cancelOrder: 乐观更新 holdings.orders[i].status = '51' (待撤), 等 push 改终态
 */
export const useOrderStore = defineStore('order', () => {
  // 不再持有独立 orders/trades, 全部走 holdings store
  // 保留 loading 状态供 Trade.vue 按钮禁用
  const placing = ref(false)
  const cancelling = ref(false)

  /**
   * 下单后立即写缓存（关键: 推送匹配需要 order_no 在缓存里）
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
    // placeOrder 跟 createOrder 等价(后端同一接口, 统一返 list[0])
    // 下单前 sysconfig 检查 — confirm_before_order=true → 弹二次确认 (全站生效)
    //   此处统一拦截所有 placeOrder 调用方: Trade.vue / T0Trade.vue / useT0OrderSubmit.js
    //   sysconfig 缺失视为关闭 (默认 false)
    if (await _shouldConfirmBeforeOrder()) {
      try {
        await ElMessageBox.confirm(
          _buildConfirmMessage(orderData),
          '下单前二次确认',
          { confirmButtonText: '确认下单', cancelButtonText: '取消', type: 'warning' }
        )
      } catch (e) {
        // 用户取消 → 不下单, 抛错让调用方 catch
        throw new Error('用户取消下单')
      }
    }
    return await createOrder(orderData)
  }

  /**
   * 读 sysconfig.confirm_before_order, 缓存 60s 避免每次下单打后端
   *   - 返回 bool: true = 需要弹二次确认
   *   - sysconfig 读取失败 → 默认 false (不弹)
   *   - 简单内存缓存, 进程内; 用户改 sysconfig 后等 ≤60s 生效 (或刷新页面)
   */
  let _confirmCache = null
  let _confirmCacheAt = 0
  async function _shouldConfirmBeforeOrder() {
    const now = Date.now()
    if (_confirmCache !== null && (now - _confirmCacheAt) < 60000) return _confirmCache
    try {
      const r = await sysconfigApi.get('confirm_before_order')
      // r 可能 {cfg_val: 'true'|'false', value: 'true'|...} - 多后端字段兼容
      const val = r?.cfg_val ?? r?.value ?? r
      _confirmCache = val === true || val === 'true' || val === 1 || val === '1'
    } catch {
      _confirmCache = false
    }
    _confirmCacheAt = now
    return _confirmCache
  }

  /**
   * 二次确认弹窗展示文案的精简版 (避免弹窗太高)
   *   只列最关键的: 标的 / 方向 / 数量 / 价格 (限价时)
   */
  function _buildConfirmMessage(d) {
    const direction = d.order_type === '23' ? '买' : d.order_type === '24' ? '卖' : d.order_type
    const lines = [
      `标的: ${d.stock_code || '—'}`,
      `方向: ${direction}`,
      `数量: ${(d.volume ?? 0).toLocaleString()} 股`,
    ]
    if (d.price !== undefined && d.price !== null && Number(d.price) > 0) {
      lines.push(`价格: ¥${d.price}`)
    }
    return lines.join('\n')
  }

  async function cancelOrder(orderNo, trdDate) {
    cancelling.value = true
    try {
      // 撤单用 order_no + trd_date；status 由 ord_cfm push 异步改, 不本地写
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
    // 不暴露 orders/trades getter, view 必须显式 useHoldingsStore().orders
    //     避免"看起来是 orderStore 独立缓存"误解, 强制走单一源
  }
})
