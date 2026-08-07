<!--
  CacheAsset.vue — 资金缓存查看 (IDB/Pinia 单行数据)

  数据源: useHoldingsStore().cachedAsset (单一源)
  单行对象, 用 stats cards 展示, 不需要表格/分页
-->
<template>
  <div class="cache-asset-view fade-in-up">
    <section class="stats-grid">
      <div class="stat-card" v-for="field in fields" :key="field.key">
        <div class="stat-icon" v-if="field.icon">{{ field.icon }}</div>
        <div class="stat-label">{{ field.label }}</div>
        <div class="stat-value text-mono">{{ formatValue(field.key) }}</div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useHoldingsStore } from '../stores/holdings'
import { formatMoney } from '../utils/format'

const holdingsStore = useHoldingsStore()
const asset = computed(() => holdingsStore.cachedAsset || {})

const fields = [
  { key: 'cash', label: '现金', format: (v) => formatMoney(v) },
  { key: 'available', label: '可用资金', format: (v) => formatMoney(v) },
  { key: 'frozen_cash', label: '冻结资金', format: (v) => formatMoney(v) },
  { key: 'market_value', label: '持仓市值', format: (v) => formatMoney(v) },
  { key: 'total_asset', label: '总资产', format: (v) => formatMoney(v) },
  { key: 'last_asset', label: '期初总资产', format: (v) => formatMoney(v) },
]

function formatValue(key) {
  const field = fields.find((f) => f.key === key)
  const value = asset.value[key]
  if (value == null) return '—'
  return field?.format ? field.format(value) : value
}
</script>

<style scoped>
.cache-asset-view { display: flex; flex-direction: column; gap: var(--space-5); }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-4); }
.stat-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-5) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.stat-label { font-size: 13px; color: var(--text-secondary); font-weight: 500; }
.stat-value { font-size: 22px; font-weight: 700; }
.text-mono { font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace); }
@media (max-width: 900px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .stats-grid { grid-template-columns: 1fr; } }
</style>
