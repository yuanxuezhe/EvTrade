/**
 * useT0OrderSubmit — T0 下单核心封装
 *
 * phase-2 拆分: T0Trade.vue submitOrder ~40 行
 * 包含: 价格类型映射、orderStore.placeOrder 调用、ElMessage 成功/失败提示、错误码分支
 *
 * 入参:
 *   refs:
 *     - stockCode: Ref<string>
 *     - priceType: Ref<'market'|'oppose'|'latest'|'limit'>
 *     - balanceCoeff: Ref<number>
 *     - submitting: Ref<boolean>  (双向, 用于 UI loading)
 *   stores:
 *     - orderStore (useOrderStore 实例)
 *   hooks:
 *     - onAfterSuccess?: () => void  (默认空, 通常用于 loadT0Stats)
 *
 * 返回: { submitOrder(params) }
 *   params: { orderType: '23'|'24', volume: number, price: number }
 */
import { ElMessage } from 'element-plus'
import { formatPrice } from '../utils/format'

export function useT0OrderSubmit({ stockCode, priceType, balanceCoeff, submitting, orderStore, onAfterSuccess }) {
  async function submitOrder({ orderType, volume, price, taskId = null }) {
    submitting.value = true
    try {
      const priceTypeCode = priceType.value === 'market' ? 44
        : priceType.value === 'oppose' ? 14
        : 11  // 'latest' / 'limit'
      // v8: 走 orderStore 统一处理（已 _upsertToHoldings 写缓存 + 防御性 status 重算）
      //     res = api 拦截器解包后的 list 数组(1 个 OrderOut)
      const res = await orderStore.placeOrder({
        stock_code: stockCode.value,
        order_type: orderType,
        price_type: priceTypeCode,
        price: price,
        volume: volume,
        t0_coefficient: balanceCoeff.value,
        user_def: 'T0',  // T0 页面下单调标记
        ...(taskId ? { task_id: taskId } : {}),  // v18: 选定的 task 写回 (向后兼容 = null)
      })
      if (res) {
        const dir = orderType === '23' ? '买' : '卖'
        ElMessage.success(`${dir}单已报：${volume} 股 @ ¥${formatPrice(price)}`)
        if (onAfterSuccess) onAfterSuccess()
      } else {
        ElMessage.error('下单失败')
      }
    } catch (e) {
      const detail = e?.response?.data?.detail
      const code = detail?.code
      if (code === 'TRADING_DAY_NOT_INIT') {
        // 日初未做：仅提示，由用户在左侧菜单进入「系统初始化」处理
        ElMessage.warning(detail?.msg || '当前未做日初，请到「系统初始化」处理')
      } else if (code === 'OUTSIDE_TRADING_SESSION') {
        ElMessage.warning(detail?.msg || '非交易时段，仅可查询')
      } else {
        ElMessage.error(detail?.msg || e.message || '下单失败')
      }
    } finally {
      submitting.value = false
    }
  }

  return { submitOrder }
}
