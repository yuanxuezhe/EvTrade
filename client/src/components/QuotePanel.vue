<template>
  <div class="quote-panel content-card">
    <!-- 标题 + 标的 -->
    <div class="qp-header">
      <div class="qp-title">
        <el-icon><DataLine /></el-icon>
        <span>行情面板</span>
        <span v-if="code" class="qp-stock-code">{{ code }}</span>
      </div>
      <span v-if="lastPriceText" class="qp-last-time">更新 {{ updatedAgo }}</span>
    </div>

    <!-- ① 顶部：最新价 + 涨跌幅（核心）：未订阅时显示占位 -->
    <div class="qp-hero" :class="heroClass">
      <div class="qp-hero-price">{{ lastPriceText }}</div>
      <div class="qp-hero-chg">
        <span>{{ changeText }}</span>
        <span class="qp-hero-pct">{{ changePctText }}</span>
      </div>
      <span v-if="!code" class="qp-hero-hint">输入股票代码订阅行情</span>
    </div>

    <!-- ② 中部：6 字段（开/高/低/昨收/量/额） -->
    <div class="qp-grid">
      <div class="qp-cell" @dblclick="emitApply(quote?.fields?.[FIELD.OPEN])" title="双击带入限价">
        <span class="qp-cell-label">今开</span>
        <span class="qp-cell-value">{{ formatNum(quote?.fields?.[FIELD.OPEN]) }}</span>
      </div>
      <div class="qp-cell" @dblclick="emitApply(quote?.fields?.[FIELD.HIGH])" title="双击带入限价">
        <span class="qp-cell-label">最高</span>
        <span class="qp-cell-value">{{ formatNum(quote?.fields?.[FIELD.HIGH]) }}</span>
      </div>
      <div class="qp-cell" @dblclick="emitApply(quote?.fields?.[FIELD.LOW])" title="双击带入限价">
        <span class="qp-cell-label">最低</span>
        <span class="qp-cell-value">{{ formatNum(quote?.fields?.[FIELD.LOW]) }}</span>
      </div>
      <div class="qp-cell" @dblclick="emitApply(quote?.fields?.[FIELD.PREV_CLOSE])" title="双击带入限价（昨收）">
        <span class="qp-cell-label">昨收</span>
        <span class="qp-cell-value">{{ formatNum(quote?.fields?.[FIELD.PREV_CLOSE]) }}</span>
      </div>
      <div class="qp-cell">
        <span class="qp-cell-label">成交量</span>
        <span class="qp-cell-value">{{ formatBigNum(quote?.fields?.[FIELD.VOLUME]) }}</span>
      </div>
      <div class="qp-cell">
        <span class="qp-cell-label">成交额</span>
        <span class="qp-cell-value">{{ formatBigNum(quote?.fields?.[FIELD.AMOUNT]) }}</span>
      </div>
    </div>

    <!-- ③ 5 档盘口（卖5..卖1 + 最新价 + 买1..买5）—— 未订阅时仍显示空骨架 -->
    <div class="qp-orderbook" :class="{ 'is-empty': !quote }">
      <div class="qp-ob-head">
        <span class="qp-ob-label ask">卖盘</span>
        <span class="qp-ob-label">最新</span>
        <span class="qp-ob-label bid">买盘</span>
      </div>
      <div
        v-for="i in 5"
        :key="i"
        class="qp-ob-row"
      >
        <!-- 卖5..卖1（i=5→1 倒序） -->
        <div
          class="qp-ob-cell ask"
          @dblclick="emitApply(getAskPrice(6 - i))"
          title="双击带入限价（卖盘）"
        >
          <span class="qp-ob-rank">卖{{ 6 - i }}</span>
          <span class="qp-ob-price">{{ formatNum(getAskPrice(6 - i)) }}</span>
          <span class="qp-ob-vol">{{ formatBigNum(getAskVol(6 - i)) }}</span>
        </div>
        <!-- 最新价列（中间，第 3 列高亮） -->
        <div
          v-if="i === 3"
          class="qp-ob-cell mid"
          :class="heroClass"
        >
          <span class="qp-ob-mid-price">{{ lastPriceText }}</span>
        </div>
        <div v-else class="qp-ob-cell mid empty"></div>
        <!-- 买1..买5 -->
        <div
          class="qp-ob-cell bid"
          @dblclick="emitApply(getBidPrice(i))"
          title="双击带入限价（买盘）"
        >
          <span class="qp-ob-rank">买{{ i }}</span>
          <span class="qp-ob-price">{{ formatNum(getBidPrice(i)) }}</span>
          <span class="qp-ob-vol">{{ formatBigNum(getBidVol(i)) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { DataLine } from '@element-plus/icons-vue'
import { useQuoteStore, FIELD as F } from '../stores/quote'

const props = defineProps({
  stockCode: { type: String, default: '' }
})

const emit = defineEmits(['apply-price'])

const quoteStore = useQuoteStore()
const FIELD = F  // 模板里直接用 FIELD.X

const tick = ref(0)  // 每秒 tick 一次用于刷新"X秒前"
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
const lastPrice = computed(() => quote.value?.last_price ?? null)
const lastPriceText = computed(() => {
  const v = lastPrice.value
  if (v == null || !Number.isFinite(v)) return '—'
  return String(v)
})

const changePct = computed(() => {
  const q = quote.value
  if (!q || !q.fields) return null
  const last = Number(q.fields[F.LAST])
  const prev = Number(q.fields[F.PREV_CLOSE])
  if (!Number.isFinite(last) || !Number.isFinite(prev) || prev === 0) return null
  return ((last - prev) / prev) * 100
})
const changePctText = computed(() => {
  const v = changePct.value
  if (v == null) return '—'
  const sign = v > 0 ? '+' : v < 0 ? '' : ''
  return `${sign}${v.toFixed(2)}%`
})
const changeText = computed(() => {
  const q = quote.value
  if (!q || !q.fields) return '—'
  const last = Number(q.fields[F.LAST])
  const prev = Number(q.fields[F.PREV_CLOSE])
  if (!Number.isFinite(last) || !Number.isFinite(prev)) return '—'
  const diff = last - prev
  return `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}`
})
const heroClass = computed(() => {
  const v = changePct.value
  if (v == null) return ''
  if (v > 0) return 'text-up'      // 涨红
  if (v < 0) return 'text-down'   // 跌绿
  return 'text-flat'              // 平黑
})

const updatedAgo = computed(() => {
  const q = quote.value
  if (!q) return ''
  const sec = Math.max(0, Math.floor((Date.now() - q.ts) / 1000))
  if (sec < 60) return `${sec}s 前`
  if (sec < 3600) return `${Math.floor(sec / 60)}m 前`
  return new Date(q.ts).toLocaleTimeString()
})

// 5 档盘口取值
function getAskPrice(level) {  // level 1..5
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

// 格式化：保留原始精度（行情原始数据）
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

// 双击：带入限价（emit 给父组件 Trade.vue 统一处理）
function emitApply(v) {
  if (v == null || v === '') return
  const n = Number(v)
  if (!Number.isFinite(n) || n <= 0) return
  emit('apply-price', n)
}

onBeforeUnmount(() => stopTick())
startTick()
</script>

<style scoped>
.quote-panel { padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 10px; }
.qp-header { display: flex; align-items: center; justify-content: space-between; }
.qp-title { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--text-primary, #1f2329); }
.qp-title .el-icon { color: var(--primary-color, #2d6cdf); }
.qp-stock-code { font-family: 'Roboto Mono', monospace; color: var(--text-secondary, #6b7785); font-weight: 500; }
.qp-last-time { font-size: 12px; color: var(--text-tertiary, #8f95a1); }
.qp-empty { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 24px 0; color: var(--text-tertiary, #8f95a1); font-size: 13px; }

/* 最新价 标题区 */
.qp-hero { display: flex; align-items: baseline; gap: 16px; padding: 6px 0 4px; }
.qp-hero-price { font-size: 32px; font-weight: 700; font-family: 'Roboto Mono', monospace; letter-spacing: -0.5px; }
.qp-hero-chg { display: flex; align-items: baseline; gap: 6px; font-size: 14px; font-family: 'Roboto Mono', monospace; }
.qp-hero-pct { font-weight: 600; }
.qp-hero-hint { font-size: 12px; color: var(--text-tertiary, #8f95a1); margin-left: auto; font-weight: 400; font-family: inherit; }

/* 6 格字段 */
.qp-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.qp-cell {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 8px 4px; border-radius: 4px;
  background: var(--bg-secondary, #f5f6f8); cursor: pointer; transition: background .15s;
  user-select: none;
}
.qp-cell:hover { background: var(--bg-hover, #e9ecf2); }
.qp-cell-label { font-size: 11px; color: var(--text-tertiary, #8f95a1); margin-bottom: 2px; }
.qp-cell-value { font-size: 13px; font-weight: 600; font-family: 'Roboto Mono', monospace; color: var(--text-primary, #1f2329); }

/* 5 档盘口 */
.qp-orderbook { display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--border-color, #e5e6eb); border-radius: 4px; padding: 4px 0; background: var(--bg-secondary, #fafbfc); transition: opacity .2s; }
.qp-orderbook.is-empty { opacity: .55; }
.qp-ob-head { display: grid; grid-template-columns: 1fr 1fr 1fr; padding: 2px 8px; }
.qp-ob-label { font-size: 11px; color: var(--text-tertiary, #8f95a1); }
.qp-ob-label.ask { color: var(--color-down, #16b572); text-align: left; }
.qp-ob-label.bid { color: var(--color-up, #f5475d); text-align: right; }
.qp-ob-label:not(.ask):not(.bid) { text-align: center; }

.qp-ob-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 2px; padding: 2px 4px; }
.qp-ob-cell { display: grid; grid-template-columns: auto 1fr auto; gap: 6px; padding: 3px 6px; border-radius: 3px; font-family: 'Roboto Mono', monospace; font-size: 12px; cursor: pointer; transition: background .15s; user-select: none; }
.qp-ob-cell:hover { background: var(--bg-hover, #e9ecf2); }
.qp-ob-cell.ask .qp-ob-rank { color: var(--color-down, #16b572); }
.qp-ob-cell.bid .qp-ob-rank { color: var(--color-up, #f5475d); }
.qp-ob-rank { width: 26px; font-size: 11px; }
.qp-ob-price { text-align: right; font-weight: 600; }
.qp-ob-vol { width: 42px; text-align: right; color: var(--text-tertiary, #8f95a1); font-size: 11px; }
.qp-ob-cell.mid { display: flex; align-items: center; justify-content: center; background: var(--bg-primary, #fff); cursor: default; }
.qp-ob-cell.mid.empty { background: transparent; }
.qp-ob-mid-price { font-weight: 700; font-size: 14px; }

/* 颜色 */
.text-up { color: var(--color-up, #f5475d); }
.text-down { color: var(--color-down, #16b572); }
.text-flat { color: var(--text-primary, #1f2329); }
</style>