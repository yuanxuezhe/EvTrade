<!--
  LivePriceCell.vue — 通用 cell: 最新价 + 涨跌幅 (一行显示, 红绿配色)

  设计目标:
    - 单一职责: 渲染一只股票的最新价 + 涨跌幅 (跟行情推送实时联动)
    - 三处复用: Trade (HoldingsPanel 嵌入) / T0Trade 自有 last_price 列 / 持仓查询 CachePositions
    - 数据源: quoteStore (last_price + getChangePct 内置), 不轮询, 靠 quoteTickTrigger 触发响应式
    - 与 HoldingsPanel priceClass 一致: 高于昨收红 (text-up), 低于昨收绿 (text-down)
    - 持仓表格里通常用 "最新价" 列 header, 但实际是 "最新价(涨跌幅)" 语义
      → 该组件内部同时渲染两个值, 列 header 也可写 "最新价(涨跌幅)"

  Props:
    stockCode  String  必填, 行情快照的股票代码

  行为:
    - 有最新价: 显示价格 + 涨跌幅 (e.g. "1820.50 +1.23%")
    - 涨跌幅为 0 或 ±无穷 (除以零) 显示为 flat
    - 都没数据: 显示 "—"
-->
<template>
  <span class="live-price-cell">
    <span v-if="lastPrice != null" class="text-mono price" :class="priceClass">
      {{ formatPrice(lastPrice, stockCode) }}
    </span>
    <span v-else class="text-muted price">—</span>
    <span
      v-if="changePct != null"
      class="text-mono pct"
      :class="pctClass"
      style="margin-left: 4px; font-size: 12px"
    >
      {{ changePct > 0 ? '+' : '' }}{{ Number(changePct).toFixed(2) }}%
    </span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useQuoteStore } from '../../stores/quote'
import { formatPrice } from '../../composables/usePricePrecision'

const props = defineProps({
  // 2026-08-21: 取消 required, 允许父组件传 undefined (持仓表里某行 stock_code 缺失 / 

  //   临时过滤行 时不报错, 显示空 cell)
  stockCode: { type: String, default: '' },
})

const quoteStore = useQuoteStore()

const hasCode = computed(() => !!props.stockCode)

// 行情推送触发响应式 — quoteStore.size / getChangePct 内部已自动追踪
const lastPrice = computed(() => {
  if (!hasCode.value) return null
  const q = quoteStore.get(props.stockCode)
  return q?.last_price != null ? Number(q.last_price) : null
})

const changePct = computed(() => {
  if (!hasCode.value) return null
  return quoteStore.getChangePct(props.stockCode)
})

const prevClose = computed(() => {
  if (!hasCode.value) return null
  const q = quoteStore.get(props.stockCode)
  return q?.prev_close != null ? Number(q.prev_close) : null
})

const priceClass = computed(() => {
  if (lastPrice.value == null || prevClose.value == null || prevClose.value === 0) return ''
  if (lastPrice.value > prevClose.value) return 'text-up'
  if (lastPrice.value < prevClose.value) return 'text-down'
  return 'text-flat'
})

const pctClass = computed(() => {
  if (changePct.value == null || !Number.isFinite(changePct.value)) return ''
  if (changePct.value > 0) return 'text-up'
  if (changePct.value < 0) return 'text-down'
  return 'text-flat'
})
</script>

<style scoped>
.live-price-cell {
  display: inline-flex;
  align-items: baseline;
  gap: 0;
}
</style>
