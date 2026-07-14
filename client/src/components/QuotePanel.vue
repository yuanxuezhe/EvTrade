<!--
  QuotePanel.vue — 行情面板（v15.1 quote-panel-template-match r3）

  按 broker 终端 行情模板.png 重排版 (r3 修订):
    头部 (Symbol + 名+码, 码字大) → hero (大最新价 + 涨跌, 可点)
    → 卖盘纵栈 (5→1, 单击带价)
    → 买盘纵栈 (1→5, 单击带价)
    → 16 格 stats grid (含昨收, 价格格均可点)

  r3 删除:
    - 委比/委差 row (后端不支持, 视觉冗余)
    - 卖 1 / 买 1 中间的"最新价"浮标 (hero 已显示, 重复)

  交互:
    - 所有"价格"cells 单击带入 OrderForm 委托价 (替代 v14 双击)
    - 卖/买 5 档价 + hero 最新价 + stats grid 7 个价格格 (昨收/开盘/最高/最低/均价/涨停/跌停)
    - hover 态 + tooltip 提示可点击

  衍生字段 (client-side 计算):
    - 均价 / 振幅 / 涨停 / 跌停
    - 后端未支持字段 (现手 / 量比 / 市值 / 费率) 显示 `—`
-->
<template>
  <div class="quote-panel content-card">
    <!-- ① 头部: Symbol + 名 + 码 -->
    <div class="qp-header">
      <span class="qp-symbol" :class="heroClass">{{ statusSymbol }}</span>
      <span class="qp-name">{{ stockName }}</span>
      <span class="qp-code">{{ code }}</span>
    </div>

    <!-- ② hero: 大最新价 + 涨跌 + 涨跌幅 (可点击带价) -->
    <div
      class="qp-hero"
      :class="[heroClass, { 'is-clickable': lastPrice != null }]"
      :title="lastPrice != null ? '点击带入委托价' : ''"
      @click="emitApply(lastPrice)"
    >
      <span class="qp-hero-price">{{ lastPriceText }}</span>
      <span class="qp-hero-chg">{{ changeText }}</span>
      <span class="qp-hero-pct">{{ changePctText }}</span>
    </div>

    <!-- ③ 卖盘纵栈 (5→1) — 单击带价 -->
    <div class="qp-stack qp-stack-ask">
      <div
        v-for="i in 5"
        :key="`ask-${i}`"
        class="qp-row qp-row-ask"
        :class="{ 'is-disabled': !hasAsk(i) }"
        :title="hasAsk(i) ? '点击带入委托价' : '无该档行情'"
        @click="emitApply(getAskPrice(i))"
      >
        <span class="qp-rank">卖{{ 6 - i }}</span>
        <span class="qp-price" :class="heroClass">{{ formatNum(getAskPrice(6 - i)) }}</span>
        <span class="qp-vol">{{ formatBigNum(getAskVol(6 - i)) }}</span>
      </div>
    </div>

    <!-- ④ 买盘纵栈 (1→5) — 单击带价 -->
    <div class="qp-stack qp-stack-bid">
      <div
        v-for="i in 5"
        :key="`bid-${i}`"
        class="qp-row qp-row-bid"
        :class="{ 'is-disabled': !hasBid(i) }"
        :title="hasBid(i) ? '点击带入委托价' : '无该档行情'"
        @click="emitApply(getBidPrice(i))"
      >
        <span class="qp-rank">买{{ i }}</span>
        <span class="qp-price" :class="heroClass">{{ formatNum(getBidPrice(i)) }}</span>
        <span class="qp-vol">{{ formatBigNum(getBidVol(i)) }}</span>
      </div>
    </div>

    <!-- ⑤ 16 格 stats grid (label-left / value-right; 价格格均可点) -->
    <div class="qp-stats-grid">
      <div
        class="qp-stats-cell is-clickable"
        :title="prevClose != null ? '点击带入委托价' : ''"
        @click="emitApply(prevClose)"
      ><span class="qp-cell-label">昨收</span><span class="qp-cell-value" :class="heroClass">{{ formatNum(prevClose) }}</span></div>
      <div
        class="qp-stats-cell is-clickable"
        :title="(quote?.fields?.[F.OPEN] != null && Number(quote?.fields?.[F.OPEN]) > 0) ? '点击带入委托价' : ''"
        @click="emitApply(quote?.fields?.[F.OPEN])"
      ><span class="qp-cell-label">开盘</span><span class="qp-cell-value" :class="heroClass">{{ formatNum(quote?.fields?.[F.OPEN]) }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">涨跌</span><span class="qp-cell-value" :class="signClass(changeNum)">{{ changeText }}</span></div>
      <div
        class="qp-stats-cell is-clickable"
        :title="(quote?.fields?.[F.HIGH] != null && Number(quote?.fields?.[F.HIGH]) > 0) ? '点击带入委托价' : ''"
        @click="emitApply(quote?.fields?.[F.HIGH])"
      ><span class="qp-cell-label">最高</span><span class="qp-cell-value" :class="heroClass">{{ formatNum(quote?.fields?.[F.HIGH]) }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">涨幅</span><span class="qp-cell-value" :class="signClass(changePct)">{{ changePctText }}</span></div>
      <div
        class="qp-stats-cell is-clickable"
        :title="(quote?.fields?.[F.LOW] != null && Number(quote?.fields?.[F.LOW]) > 0) ? '点击带入委托价' : ''"
        @click="emitApply(quote?.fields?.[F.LOW])"
      ><span class="qp-cell-label">最低</span><span class="qp-cell-value" :class="heroClass">{{ formatNum(quote?.fields?.[F.LOW]) }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">振幅</span><span class="qp-cell-value">{{ amplitudeText }}</span></div>
      <div
        class="qp-stats-cell is-clickable"
        :title="avgPrice != null ? '点击带入委托价' : ''"
        @click="emitApply(avgPrice)"
      ><span class="qp-cell-label">均价</span><span class="qp-cell-value">{{ avgPriceText }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">现手</span><span class="qp-cell-value">—</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">金额</span><span class="qp-cell-value">{{ formatBigNum(quote?.fields?.[F.AMOUNT]) }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">总手</span><span class="qp-cell-value">{{ formatBigNum(quote?.fields?.[F.VOLUME]) }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">量比</span><span class="qp-cell-value">—</span></div>
      <div
        class="qp-stats-cell is-clickable"
        :title="limitUp != null ? '点击带入委托价' : ''"
        @click="emitApply(limitUp)"
      ><span class="qp-cell-label">涨停</span><span class="qp-cell-value text-up">{{ limitUpText }}</span></div>
      <div
        class="qp-stats-cell is-clickable"
        :title="limitDown != null ? '点击带入委托价' : ''"
        @click="emitApply(limitDown)"
      ><span class="qp-cell-label">跌停</span><span class="qp-cell-value text-down">{{ limitDownText }}</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">市值</span><span class="qp-cell-value">—</span></div>
      <div class="qp-stats-cell"><span class="qp-cell-label">费率</span><span class="qp-cell-value">—</span></div>
    </div>

    <!-- 未订阅提示 -->
    <div v-if="!code" class="qp-empty">输入股票代码订阅行情</div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useQuoteStore, FIELD } from '../stores/quote'

const props = defineProps({
  stockCode: { type: String, default: '' }
})

const emit = defineEmits(['apply-price'])

const quoteStore = useQuoteStore()
const F = FIELD

// 2026-07-09 quote-snapshot-subscribe:
//   - 监听 props.stockCode 变化, 当用户输入新代码 (debounce 300ms) 自动调订阅
//   - 面板卸载时, 取消本面板持有的订阅 (避免幽灵订阅占 ws_manager)
//   - 注意: 持仓页/Trade 页可能同时订阅同一 code,
//     subscribedSet 用 Set 自动去重, unsubscribe 也只是减引用计数, 不影响其他消费者
let _currentCode = ''
let _debounceTimer = null
let _subscribed = false  // 本组件是否真的订阅过 (避免卸载时误 cancel 未订阅的)
watch(
  () => props.stockCode,
  (newCode) => {
    if (_debounceTimer) { clearTimeout(_debounceTimer); _debounceTimer = null }
    const c = (newCode || '').toUpperCase().trim()
    if (!c) {
      // 清空时立即取消订阅
      if (_subscribed && _currentCode) {
        quoteStore.unsubscribe([_currentCode])
        _subscribed = false
      }
      _currentCode = ''
      return
    }
    // 300ms debounce: 用户连续输 "000001.SZ" 时, 避免对每个字符都发订阅请求
    _debounceTimer = setTimeout(() => {
      // 切换 code: 取消旧的 (如果之前订过)
      if (_subscribed && _currentCode && _currentCode !== c) {
        quoteStore.unsubscribe([_currentCode])
      }
      // 订新的 (如果未订过)
      if (!_subscribed || _currentCode !== c) {
        quoteStore.subscribe([c])
        _subscribed = true
      }
      _currentCode = c
    }, 300)
  },
  { immediate: true }  // 首次挂载如果已有 code, 立即订
)

const tick = ref(0)
let timer = null
function startTick() {
  if (timer) return
  timer = setInterval(() => { tick.value++ }, 1000)
}
function stopTick() {
  if (timer) { clearInterval(timer); timer = null }
}

const code = computed(() => (props.stockCode || '').toUpperCase().trim())
const quote = computed(() => (tick.value, quoteStore.get(code.value)))

const stockName = computed(() => {
  // 行情数据未携带股票名, 暂回退空 (trader 看代码)
  return ''
})

const lastPrice = computed(() => {
  const q = quote.value
  if (!q) return null
  return q.last_price ?? Number(q.fields?.[F.LAST]) ?? null
})
const lastPriceText = computed(() => formatNum(lastPrice.value))

const prevClose = computed(() => Number(quote.value?.fields?.[F.PREV_CLOSE]) || null)

const changeNum = computed(() => {
  const last = lastPrice.value
  const prev = prevClose.value
  if (last == null || prev == null) return null
  return Number(last) - Number(prev)
})
const changeText = computed(() => {
  const v = changeNum.value
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}`
})

const changePct = computed(() => {
  const last = Number(lastPrice.value)
  const prev = Number(prevClose.value)
  if (!Number.isFinite(last) || !Number.isFinite(prev) || prev === 0) return null
  return ((last - prev) / prev) * 100
})
const changePctText = computed(() => {
  const v = changePct.value
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
})

const heroClass = computed(() => {
  const v = changePct.value
  if (v == null) return ''
  if (v > 0) return 'text-up'
  if (v < 0) return 'text-down'
  return 'text-flat'
})

const statusSymbol = computed(() => {
  const v = changePct.value
  if (v == null) return '·'
  if (v > 0) return '▲'
  if (v < 0) return '▼'
  return '▬'
})

// ─── 衍生: 均价 / 振幅 / 涨/跌停 ───
const avgPrice = computed(() => {
  const q = quote.value
  if (!q || !q.fields) return null
  const amount = Number(q.fields[F.AMOUNT])
  const volume = Number(q.fields[F.VOLUME])
  if (!Number.isFinite(amount) || !Number.isFinite(volume) || volume === 0) return null
  return amount / volume
})
const avgPriceText = computed(() => avgPrice.value != null ? avgPrice.value.toFixed(3) : '—')

const amplitude = computed(() => {
  const q = quote.value
  if (!q || !q.fields) return null
  const high = Number(q.fields[F.HIGH])
  const low = Number(q.fields[F.LOW])
  const prev = Number(q.fields[F.PREV_CLOSE])
  if (!Number.isFinite(high) || !Number.isFinite(low) || !Number.isFinite(prev) || prev === 0) return null
  return ((high - low) / prev) * 100
})
const amplitudeText = computed(() => amplitude.value != null ? `${amplitude.value.toFixed(2)}%` : '—')

// TODO 区分板块: 创业板/科创板 20%, ST 5%; 当前简化为主板 10%
const limitUp = computed(() => prevClose.value != null ? Number((prevClose.value * 1.10).toFixed(2)) : null)
const limitDown = computed(() => prevClose.value != null ? Number((prevClose.value * 0.90).toFixed(2)) : null)
const limitUpText = computed(() => limitUp.value != null ? limitUp.value.toFixed(2) : '—')
const limitDownText = computed(() => limitDown.value != null ? limitDown.value.toFixed(2) : '—')

// ─── 5 档盘口 ───
function getAskPrice(level) {
  return quote.value?.fields?.[F.ASK_PRICE + (level - 1)] ?? null
}
function getBidPrice(level) {
  return quote.value?.fields?.[F.BID_PRICE + (level - 1)] ?? null
}
function getAskVol(level) {
  return quote.value?.fields?.[F.ASK_VOL + (level - 1)] ?? null
}
function getBidVol(level) {
  return quote.value?.fields?.[F.BID_VOL + (level - 1)] ?? null
}
function hasAsk(level) {
  const p = getAskPrice(level)
  return p != null && Number(p) > 0
}
function hasBid(level) {
  const p = getBidPrice(level)
  return p != null && Number(p) > 0
}

// ─── 格式化 ───
function formatNum(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (n === 0) return '0'
  return String(n)
}
function formatBigNum(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN')
}
function signClass(v) {
  if (v == null || !Number.isFinite(Number(v))) return ''
  const n = Number(v)
  if (n > 0) return 'text-up'
  if (n < 0) return 'text-down'
  return 'text-flat'
}

// ─── 单击: 带入限价 ───
function emitApply(v) {
  if (v == null || v === '') return
  const n = Number(v)
  if (!Number.isFinite(n) || n <= 0) return
  emit('apply-price', n)
}

onBeforeUnmount(() => {
  stopTick()
  // 2026-07-09 quote-snapshot-subscribe: 面板卸载, 取消本组件订阅
  if (_debounceTimer) { clearTimeout(_debounceTimer); _debounceTimer = null }
  if (_subscribed && _currentCode) {
    quoteStore.unsubscribe([_currentCode])
    _subscribed = false
  }
})
startTick()
</script>

<style scoped>
.quote-panel {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-family: 'Roboto Mono', 'Menlo', monospace;
  font-size: 13px;
  /* v32: 修 commit 4 副作用 — 五档 + 11 个数据格 在 206.5px cell 内溢出, 加纵向滚动 */
  overflow-y: auto;
  min-height: 0;
}

/* ① 头部 */
.qp-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  border-bottom: 1px solid var(--border-light);
  padding-bottom: 6px;
}
.qp-symbol { font-size: 14px; font-weight: 700; }
.qp-name { font-size: 15px; font-weight: 600; color: var(--text-primary, #1f2329); }
.qp-code {
  font-size: 18px; font-weight: 600;
  color: var(--text-secondary, #6b7785);
  margin-left: auto;
  letter-spacing: 0.5px;
}

/* ② hero (可点击带价) */
.qp-hero {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-light);
  border-radius: 3px;
  transition: background .15s;
}
.qp-hero.is-clickable { cursor: pointer; user-select: none; }
.qp-hero.is-clickable:hover { background: var(--bg-hover, #e9ecf2); }
.qp-hero-price { font-size: 30px; font-weight: 700; letter-spacing: -0.5px; }
.qp-hero-chg   { font-size: 14px; font-weight: 500; }
.qp-hero-pct   { font-size: 14px; font-weight: 600; }

/* ③ / ④ 卖/买纵栈 */
.qp-stack { display: flex; flex-direction: column; gap: 1px; }
.qp-stack-ask { background: var(--ask-tint-bg, rgba(245, 71, 93, 0.04)); border-radius: 3px; padding: 2px 0; }
.qp-stack-bid { background: var(--bid-tint-bg, rgba(22, 181, 114, 0.04)); border-radius: 3px; padding: 2px 0; }

/* 可点击行 */
.qp-row {
  display: grid;
  grid-template-columns: 56px 1fr 80px;
  align-items: center;
  padding: 4px 8px;
  cursor: pointer;
  transition: background .15s;
  user-select: none;
}
.qp-row:hover { background: var(--bg-hover, #e9ecf2); }
.qp-row.is-disabled { cursor: default; opacity: 0.4; }
.qp-rank  { font-size: 11px; color: var(--text-tertiary, #8f95a1); }
.qp-price { text-align: right; font-weight: 600; }
.qp-vol   { text-align: right; font-size: 11px; color: var(--color-vol, #2db7f5); }

/* ⑦ 16 格 stats */
.qp-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--border-light, #ebeef5);
  border-radius: 3px;
  overflow: hidden;
}
.qp-stats-cell {
  display: grid;
  grid-template-columns: 48px 1fr;
  align-items: baseline;
  padding: 4px 8px;
  background: var(--bg-elevated, #fff);
}
.qp-stats-cell.is-clickable { cursor: pointer; transition: background .15s; user-select: none; }
.qp-stats-cell.is-clickable:hover { background: var(--bg-hover, #e9ecf2); }
.qp-cell-label { font-size: 11px; color: var(--text-tertiary, #8f95a1); }
.qp-cell-value { font-size: 13px; font-weight: 600; text-align: right; color: var(--text-primary, #1f2329); }

.qp-empty {
  text-align: center;
  font-size: 12px;
  color: var(--text-tertiary, #8f95a1);
  padding: 12px 0 0;
}

/* 语义色 */
.text-up    { color: var(--color-up, #f5475d); }      /* 涨红 */
.text-down  { color: var(--color-down, #16b572); }    /* 跌绿 */
.text-flat  { color: var(--text-primary, #1f2329); }
</style>
