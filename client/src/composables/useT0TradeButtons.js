/**
 * useT0TradeButtons.js — T0Trade 主表 4 按钮 (买/卖/配平/详情) 状态计算
 *
 * 用途:
 *   - T0Trade.vue 操作列按钮的 disabled + tooltip 文案, 单一权威源
 *   - 资金/持仓校验统一走 lib/t0-calc.js 纯函数, 与 broker PriceCalc.compute_required 同口径
 *   - 不依赖 store / reactive, 接受 deps 入参 (cash / price / vol 等) → 易于测试
 *
 * 设计 (t0-trade-polish-bundle A 校验):
 *   - 买按钮: vol>0 + cash 够 + 非 submitting 才 enabled
 *   - 卖按钮: cash 方向直通 (不查), 仅校验持仓 + submitting
 *   - 配平按钮: net!=0 + (cash 够 或 持仓够, 按 side) + submitting
 *   - tooltip 文案: 缺资金 ¥X / 缺持仓 Y 股, 让 trader 知道为什么 disabled
 *
 * change t0-trade-polish-bundle (commit 2)
 */

import { calcInsufficientCash, calcInsufficientPosition } from '../lib/t0-calc'
import { calcBuyQty, calcSellQty } from './useQuickT0'


/**
 * 买按钮状态
 *
 * @param {Object} row — 持仓行 { stock_code, vol }
 * @param {Object} deps
 * @param {number} deps.pct — 全局仓位百分比 (25/50/75/100)
 * @param {number} deps.cash — 可用资金 (asset.cash)
 * @param {number} deps.price — 该 row 当前价 (lastPrice, 来自 quoteStore)
 * @param {boolean} deps.submitting — 是否正在下单
 * @returns {{disabled: boolean, tip: string, qty: number, cash: {ok: boolean, need: number, have: number, gap: number}}}
 */
export function buyBtnState(row, { pct, cash, price, submitting } = {}) {
  const code = row?.stock_code || 'N/A'
  const qty = calcBuyQty(row, pct)
  const cashCheck = calcInsufficientCash({
    side: 'buy',
    qty,
    price: Number(price) || 0,
    cash: Number(cash) || 0,
  })
  // 0 持仓买按钮 (原 isBuyDisabled 规则, 卖比 = 0 无法按比例买)
  const vol = Number(row?.vol) || 0
  const noVol = !Number.isFinite(vol) || vol <= 0
  const disabled = noVol || submitting || !cashCheck.ok
  let tip
  if (noVol) {
    tip = `${code} 持仓为 0, 无法按比例买`
  } else if (!cashCheck.ok) {
    tip = `资金 ¥${_fmtAmt(cashCheck.gap)} 不足 (需 ¥${_fmtAmt(cashCheck.need)}, 现有 ¥${_fmtAmt(cashCheck.have)})`
  } else {
    tip = `按 ${pct}% 仓位买入 ${qty} 股`
  }
  return { disabled, tip, qty, cash: cashCheck }
}


/**
 * 卖按钮状态 (卖方向不查 cash, 仅校验持仓)
 *
 * @param {Object} row
 * @param {Object} deps
 * @param {number} deps.pct
 * @param {boolean} deps.submitting
 * @returns {{disabled: boolean, tip: string, qty: number, position: {ok: boolean, need: number, have: number, gap: number}}}
 */
export function sellBtnState(row, { pct, submitting } = {}) {
  const code = row?.stock_code || 'N/A'
  const qty = calcSellQty(row, pct)
  const currentVolume = Number(row?.vol) || 0
  const posCheck = calcInsufficientPosition({ side: 'sell', qty, currentVolume })
  const disabled = submitting || !posCheck.ok
  let tip
  if (!posCheck.ok) {
    tip = `持仓 ${posCheck.have} 股不足, 缺 ${posCheck.gap} 股 (${code})`
  } else {
    tip = `按 ${pct}% 仓位卖出 ${qty} 股 (0 持仓自动跳过)`
  }
  return { disabled, tip, qty, position: posCheck }
}


/**
 * 配平按钮状态
 *
 * @param {Object} row
 * @param {Object} deps
 * @param {Object|null} deps.balance — { side, qty } 来自 netExposure, null=已配平
 * @param {number} deps.cash
 * @param {number} deps.price
 * @param {boolean} deps.submitting
 * @returns {{disabled: boolean, tip: string, side: ('buy'|'sell'|null), qty: number, gap: number}}
 */
export function balanceBtnState(row, { balance, cash, price, submitting } = {}) {
  const code = row?.stock_code || 'N/A'
  // 已配平 (net=0)
  if (!balance || !balance.side || !balance.qty) {
    return { disabled: true, tip: '已配平', side: null, qty: 0, gap: 0 }
  }
  const { side, qty } = balance
  let check
  if (side === 'buy') {
    // 净卖 → 需买 → 查 cash
    check = calcInsufficientCash({
      side: 'buy',
      qty,
      price: Number(price) || 0,
      cash: Number(cash) || 0,
    })
  } else {
    // 净买 → 需卖 → 查持仓
    check = calcInsufficientPosition({
      side: 'sell',
      qty,
      currentVolume: Number(row?.vol) || 0,
    })
  }
  const disabled = submitting || !check.ok
  let tip
  if (!check.ok) {
    if (side === 'buy') {
      tip = `资金 ¥${_fmtAmt(check.gap)} 不足, 无法配平买入 (${code})`
    } else {
      tip = `持仓 ${check.have} 股不足, 缺 ${check.gap} 股, 无法配平卖出 (${code})`
    }
  } else {
    tip = `配平: ${side === 'buy' ? `买${qty}` : `卖${qty}`} 抵消今日净敞口`
  }
  return { disabled, tip, side, qty, gap: check.gap }
}


// ---- internal ----

/** 金额简化为 K / W (避免 tooltip 太长) */
function _fmtAmt(n) {
  const v = Math.abs(Number(n) || 0)
  if (v >= 10000) return (v / 10000).toFixed(2) + 'w'
  if (v >= 1000) return (v / 1000).toFixed(2) + 'k'
  return v.toFixed(0)
}