/**
 * daypnl_livepush.test.js — 当日盈亏 live-push 流程 (v114.3)
 *
 * 复现浏览器运行时: 真实 quote store + 真实 createDayPnlRecompute + 真实 calcDayPnl
 *   - 场景 A: ws_dispatch._onQuote 转发 snapshot (含 prev_close) → day_pnl 应算出
 *   - 场景 B: live push 无 snapshot (旧行为) → prev_close undefined → day_pnl null
 */
import { setActivePinia, createPinia } from 'pinia'
import { ref, nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// quote store 依赖 http; useT0DayPnl 依赖 t0_stats api — 均 mock 掉网络
vi.mock('@/api', () => ({
  http: { get: vi.fn(), post: vi.fn() },
}))

let getExposureMock = vi.fn().mockResolvedValue({ positions: [] })
vi.mock('@/api/t0_stats', () => ({
  t0StatsApi: { getExposure: (...args) => getExposureMock(...args) },
}))

import { useQuoteStore } from '@/stores/quote'
import { createDayPnlRecompute } from '@/stores/holdings_daypnl'

async function flush() {
  await nextTick()
  await new Promise((r) => setTimeout(r, 0))
}

describe('day_pnl live-push flow (v114.3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getExposureMock.mockReset().mockResolvedValue({ positions: [] })
  })

  it('live push 带 snapshot → prev_close 写入 → day_pnl 算出非 null', async () => {
    const q = useQuoteStore()
    const positions = ref([{ stock_code: '019629.SH', last_vol: 500, vol: 500, cost_price: 1.0 }])
    const activeTrdDate = ref('20260812')
    const trades = ref([])
    const { start, stop } = createDayPnlRecompute({ positions, activeTrdDate, trades })
    start()

    // 模拟 ws_dispatch._onQuote (v114.3: 带 snapshot)
    q.update({
      stock_code: '019629.SH',
      last_price: 1.234,
      snapshot: {
        stock_code: '019629.SH', last_price: 1.234, prev_close: 1.230,
        open_price: 0, high_price: 0, low_price: 0, volume: 0, amount: 0,
      },
      fields: [],
      body: '',
    })

    await flush()
    expect(q.get('019629.SH')?.prev_close).toBe(1.23)
    expect(positions.value[0].day_pnl).not.toBeNull()
    stop()
  })

  it('live push 无 snapshot (旧行为) → prev_close undefined → day_pnl null', async () => {
    const q = useQuoteStore()
    const positions = ref([{ stock_code: '019629.SH', last_vol: 500, vol: 500 }])
    const activeTrdDate = ref('20260812')
    const trades = ref([])
    const { start, stop } = createDayPnlRecompute({ positions, activeTrdDate, trades })
    start()

    q.update({ stock_code: '019629.SH', last_price: 1.234, fields: [], body: '' })
    await flush()
    expect(q.get('019629.SH')?.prev_close).toBeUndefined()
    expect(positions.value[0].day_pnl).toBeNull()
    stop()
  })
})
