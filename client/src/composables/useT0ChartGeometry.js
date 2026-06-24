/**
 * useT0ChartGeometry — T0 收益曲线 SVG 几何计算
 *
 * phase-2 拆分: T0Trade.vue 主表 chart + drawer chart 几何重复 ~60 行
 * 抽成参数化工厂, 接受 cumHistory ref + 几何参数 (W/H/pad)
 *
 * 输入数据:
 *   cumHistory: Ref<Array<{trd_date, realized_pnl, cum_pnl}>>
 *
 * 输出:
 *   cumPath        — 累计收益折线 SVG path d
 *   cumAreaPath    — 累计收益填充区 SVG path d (含闭合到 0 线)
 *   zeroY          — 0 线 y 坐标
 *   barX(i)        — 第 i 个 bar 的 x 坐标
 *   barY(realized, i) — 第 i 个 bar 的 y 坐标（基于 realized_pnl）
 *   xLabelIndices  — X 轴标签数组（首/中/末 trd_date）
 */
import { computed } from 'vue'

/**
 * 主表 chart 几何（含 bar 计算）
 *
 * @param {Ref<Array>} cumHistory  累计收益数组 (trd_date, realized_pnl, cum_pnl)
 * @param {Object} opts            { W=800, H=200, pad=24 }
 * @returns {{cumPath, cumAreaPath, zeroY, barX, barY, xLabelIndices}}
 */
export function useT0ChartGeometry(cumHistory, opts = {}) {
  const W = opts.W ?? 800
  const H = opts.H ?? 200
  const PAD = opts.pad ?? 24

  const cumPath = computed(() => {
    const arr = cumHistory.value
    if (arr.length < 2) return ''
    const minY = Math.min(0, ...arr.map(p => p.cum_pnl))
    const maxY = Math.max(0, ...arr.map(p => p.cum_pnl))
    const range = (maxY - minY) || 1
    return arr.map((p, i) => {
      const x = (i / (arr.length - 1)) * W
      const y = H - PAD - ((p.cum_pnl - minY) / range) * (H - 2 * PAD)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
  })

  const cumAreaPath = computed(() => {
    if (!cumPath.value) return ''
    const arr = cumHistory.value
    const minY = Math.min(0, ...arr.map(p => p.cum_pnl))
    const maxY = Math.max(0, ...arr.map(p => p.cum_pnl))
    const range = (maxY - minY) || 1
    const zeroYY = H - PAD - ((0 - minY) / range) * (H - 2 * PAD)
    return cumPath.value + ` L${W},${zeroYY.toFixed(1)} L0,${zeroYY.toFixed(1)} Z`
  })

  const zeroY = computed(() => {
    const arr = cumHistory.value
    if (arr.length === 0) return H / 2
    const minY = Math.min(0, ...arr.map(p => p.cum_pnl))
    const maxY = Math.max(0, ...arr.map(p => p.cum_pnl))
    const range = (maxY - minY) || 1
    return H - PAD - ((0 - minY) / range) * (H - 2 * PAD)
  })

  function barX(i) {
    const arr = cumHistory.value
    if (arr.length <= 1) return W / 2
    return (i / (arr.length - 1)) * W
  }

  function barY(realized, i) {
    const arr = cumHistory.value
    if (arr.length === 0) return H / 2
    const minR = Math.min(0, ...arr.map(p => p.realized_pnl))
    const maxR = Math.max(0, ...arr.map(p => p.realized_pnl))
    const range = (maxR - minR) || 1
    return H - PAD - ((realized - minR) / range) * (H - 2 * PAD)
  }

  // X 轴标签（首 / 中 / 末）
  const xLabelIndices = computed(() => {
    const arr = cumHistory.value
    if (arr.length === 0) return []
    if (arr.length === 1) return [arr[0].trd_date]
    if (arr.length === 2) return [arr[0].trd_date, arr[1].trd_date]
    const mid = Math.floor(arr.length / 2)
    return [arr[0].trd_date, arr[mid].trd_date, arr[arr.length - 1].trd_date]
  })

  return { cumPath, cumAreaPath, zeroY, barX, barY, xLabelIndices, W, H, PAD }
}

/**
 * Drawer chart 几何（紧凑版, 算法略不同 - 内边距统一 PAD, 不分上下）
 *
 * @param {Ref<Array>} cumHistory  累计收益数组
 * @param {Object} opts            { W=460, H=140, pad=16 }
 * @returns {{cumPath, cumAreaPath, zeroY}}
 */
export function useT0DrawerChartGeometry(cumHistory, opts = {}) {
  const W = opts.W ?? 460
  const H = opts.H ?? 140
  const PAD = opts.pad ?? 16

  const zeroY = computed(() => {
    const pts = cumHistory.value
    if (!pts.length) return H / 2
    const max = Math.max(...pts.map(p => p.cum_pnl), 0)
    const min = Math.min(...pts.map(p => p.cum_pnl), 0)
    if (max === min) return H / 2
    return H - PAD - ((-min) / (max - min)) * (H - 2 * PAD)
  })

  const cumPath = computed(() => {
    const pts = cumHistory.value
    if (!pts.length) return ''
    const w = W - 2 * PAD
    const h = H - 2 * PAD
    const max = Math.max(...pts.map(p => p.cum_pnl), 0)
    const min = Math.min(...pts.map(p => p.cum_pnl), 0)
    const range = max - min || 1
    return pts.map((p, i) => {
      const x = PAD + (i / (pts.length - 1 || 1)) * w
      const y = PAD + (1 - (p.cum_pnl - min) / range) * h
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    }).join(' ')
  })

  const cumAreaPath = computed(() => {
    const line = cumPath.value
    if (!line) return ''
    const pts = cumHistory.value
    const max = Math.max(...pts.map(p => p.cum_pnl), 0)
    const min = Math.min(...pts.map(p => p.cum_pnl), 0)
    const range = max - min || 1
    const h = H - 2 * PAD
    const yZero = PAD + (1 - (0 - min) / range) * h
    const last = pts.length - 1
    const w = W - 2 * PAD
    const xLast = PAD + (last / (last || 1)) * w
    return `${line} L ${xLast.toFixed(1)} ${yZero.toFixed(1)} L ${PAD} ${yZero.toFixed(1)} Z`
  })

  return { cumPath, cumAreaPath, zeroY, W, H, PAD }
}
