/**
 * useT0OrderSubmit — T0 下单核心封装
 *
 * phase-2 拆分: T0Trade.vue submitOrder ~40 行
 * 包含: 价格类型映射、orderStore.placeOrder 调用、ElMessage 成功/失败提示、错误码分支
 *
 * 入参:
 *   refs:
 *     - stockCode: Ref<string>
 *     - priceType: Ref<number|'market'|'oppose'|'latest'|'limit'>
 *       - number: PriceType 常量码 (11/5/44), 推荐 (T0Trade.vue v127 改造)
 *       - string: 历史 'market'/'oppose'/'latest'/'limit', 向后兼容
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

// 价格类型 → 柜台协议码 (numeric 11/5/44). 同时接受 string (历史) 与 number (新)。
function _toPriceTypeCode(pt) {
  if (typeof pt === 'number') return pt
  // string 兼容 (历史 'market'/'oppose'/'latest'/'limit')
  if (pt === 'market' || pt === 'oppose') return 44
  if (pt === 'latest') return 5
  return 11  // 'limit' 或未知
}

export function useT0OrderSubmit({ stockCode, priceType, balanceCoeff, submitting, orderStore, onAfterSuccess }) {
  async function submitOrder({ orderType, volume, price, taskId = null, stockCodeOverride = null }) {
    submitting.value = true
    try {
      // v127: priceType 直接接受 numeric PriceType 常量 (11/5/44); string 兼容保留
      const priceTypeCode = _toPriceTypeCode(priceType.value)
      // change 2026-07-21-t0-balance-stock-code-guard: 优先用 stockCodeOverride 兜底,
      //   防止 balanceStockCode 为空时 (selectedTaskId 失效) 后端 place.py:84 校验失败.
      //   T0Trade.vue onBalanceTask 在 selectedTaskId/tasksById 失效时, 从 taskRows 直接取 row.stock_code 传入.
      const finalStockCode = stockCodeOverride || stockCode.value
      if (!finalStockCode) {
        ElMessage.warning('未选中标的，无法下单')
        submitting.value = false
        return
      }
      // v8: 走 orderStore 统一处理（已 _upsertToHoldings 写缓存 + 防御性 status 重算）
      //     res = api 拦截器解包后的 list 数组(1 个 OrderOut)
      const res = await orderStore.placeOrder({
        stock_code: finalStockCode,
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
