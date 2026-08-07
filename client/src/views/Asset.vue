<template>
  <div class="asset-view fade-in-up" v-loading="assetStore.loading">
    <!-- 总资产横幅 -->
    <section class="hero-card">
      <div class="hero-bg"></div>
      <div class="hero-content">
        <div class="hero-left">
          <div class="hero-label">账户总资产</div>
          <div class="hero-value text-mono">
            ¥{{ formatMoney(assetStore.asset.total_asset) }}
          </div>
          <div class="hero-stats">
            <div class="hero-stat">
              <span class="hs-label">现金占比</span>
              <span class="hs-value text-mono">{{ cashPercent }}%</span>
            </div>
            <div class="hero-divider"></div>
            <div class="hero-stat">
              <span class="hs-label">市值占比</span>
              <span class="hs-value text-mono">{{ marketPercent }}%</span>
            </div>
            <div class="hero-divider"></div>
            <div class="hero-stat">
              <span class="hs-label">冻结占比</span>
              <span class="hs-value text-mono">{{ frozenPercent }}%</span>
            </div>
          </div>
        </div>
        <div class="hero-right">
          <EChart :option="donutOption" height="220px" />
        </div>
      </div>
    </section>

    <!-- 资金详情卡片 -->
    <section class="cards-grid">
      <div class="asset-detail-card up">
        <div class="adc-icon">
          <el-icon :size="22"><Money /></el-icon>
        </div>
        <div class="adc-meta">
          <div class="adc-label">可用资金</div>
          <div class="adc-value text-mono">¥{{ formatMoney(assetStore.asset.cash) }}</div>
        </div>
        <div class="adc-bar">
          <div class="adc-fill up-fill" :style="{ width: cashPercent + '%' }"></div>
        </div>
        <div class="adc-percent">{{ cashPercent }}% of total</div>
      </div>

      <div class="asset-detail-card warning">
        <div class="adc-icon">
          <el-icon :size="22"><Lock /></el-icon>
        </div>
        <div class="adc-meta">
          <div class="adc-label">冻结资金</div>
          <div class="adc-value text-mono">¥{{ formatMoney(assetStore.asset.frozen_cash) }}</div>
        </div>
        <div class="adc-bar">
          <div class="adc-fill warning-fill" :style="{ width: frozenPercent + '%' }"></div>
        </div>
        <div class="adc-percent">{{ frozenPercent }}% of total</div>
      </div>

      <div class="asset-detail-card info">
        <div class="adc-icon">
          <el-icon :size="22"><DataAnalysis /></el-icon>
        </div>
        <div class="adc-meta">
          <div class="adc-label">持仓市值</div>
          <div class="adc-value text-mono">¥{{ formatMoney(assetStore.asset.market_value) }}</div>
        </div>
        <div class="adc-bar">
          <div class="adc-fill info-fill" :style="{ width: marketPercent + '%' }"></div>
        </div>
        <div class="adc-percent">{{ marketPercent }}% of total</div>
      </div>

      <div class="asset-detail-card primary">
        <div class="adc-icon">
          <el-icon :size="22"><Wallet /></el-icon>
        </div>
        <div class="adc-meta">
          <div class="adc-label">总资产</div>
          <div class="adc-value text-mono">¥{{ formatMoney(assetStore.asset.total_asset) }}</div>
        </div>
        <div class="adc-bar">
          <div class="adc-fill primary-fill" style="width: 100%"></div>
        </div>
        <div class="adc-percent">100% baseline</div>
      </div>
    </section>

    <!-- 资金构成说明 -->
    <section class="content-card info-section">
      <h3 class="info-title">资金说明</h3>
      <div class="info-grid">
        <div class="info-item">
          <div class="info-dot up-dot"></div>
          <div>
            <div class="info-name">可用资金</div>
            <div class="info-desc">账户中未被冻结的资金，可用于新委托。</div>
          </div>
        </div>
        <div class="info-item">
          <div class="info-dot warning-dot"></div>
          <div>
            <div class="info-name">冻结资金</div>
            <div class="info-desc">已被未成交委托占用的保证金。</div>
          </div>
        </div>
        <div class="info-item">
          <div class="info-dot info-dot-color"></div>
          <div>
            <div class="info-name">持仓市值</div>
            <div class="info-desc">按最新行情估算的所有持仓价值。</div>
          </div>
        </div>
        <div class="info-item">
          <div class="info-dot primary-dot"></div>
          <div>
            <div class="info-name">总资产</div>
            <div class="info-desc">可用 + 冻结 + 持仓市值。</div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { Money, Lock, DataAnalysis, Wallet } from '@element-plus/icons-vue'
import EChart from '../components/EChart.vue'
import { useAssetStore } from '../stores/asset'
import { useUiStore } from '../stores/ui'
import { formatMoney } from '../utils/format'

const assetStore = useAssetStore()
const uiStore = useUiStore()

const total = computed(() => {
  const t = Number(assetStore.asset.total_asset) || 0
  return t > 0 ? t : 1
})
const cashPercent = computed(() => Math.round(((Number(assetStore.asset.cash) || 0) / total.value) * 100))
const frozenPercent = computed(() => Math.round(((Number(assetStore.asset.frozen_cash) || 0) / total.value) * 100))
const marketPercent = computed(() => Math.round(((Number(assetStore.asset.market_value) || 0) / total.value) * 100))

const donutOption = computed(() => {
  const isDark = uiStore.theme === 'dark'
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>¥{c} ({d}%)',
      backgroundColor: isDark ? '#1a2138' : '#ffffff',
      borderColor: isDark ? '#2e3e60' : '#e8edf5',
      textStyle: { color: isDark ? '#e7ecf5' : '#1a2238' }
    },
    color: ['#4f7cff', '#ffa726', '#16b572'],
    series: [{
      type: 'pie',
      radius: ['60%', '88%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      itemStyle: {
        borderRadius: 8,
        borderColor: isDark ? '#141a2e' : '#ffffff',
        borderWidth: 3
      },
      label: { show: false },
      emphasis: {
        label: {
          show: true,
          fontSize: 13,
          fontWeight: 600,
          color: isDark ? '#e7ecf5' : '#1a2238',
          formatter: '{b}\n{d}%'
        }
      },
      labelLine: { show: false },
      data: [
        { value: Number(assetStore.asset.cash) || 0, name: '可用' },
        { value: Number(assetStore.asset.frozen_cash) || 0, name: '冻结' },
        { value: Number(assetStore.asset.market_value) || 0, name: '市值' }
      ]
    }]
  }
})

onMounted(async () => {
  await assetStore.fetchAsset()
})
</script>

<style scoped>
.asset-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
}

.hero-card {
  position: relative;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  overflow: hidden;
}

.hero-bg {
  position: absolute;
  inset: 0;
  background: var(--brand-gradient);
  opacity: 0.04;
  pointer-events: none;
}

.hero-bg::after {
  content: '';
  position: absolute;
  top: -100px;
  right: -100px;
  width: 320px;
  height: 320px;
  background: var(--brand-gradient);
  border-radius: 50%;
  opacity: 0.15;
  filter: blur(40px);
}

.hero-content {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: var(--space-6);
  align-items: center;
}

.hero-label {
  font-size: 14px;
  color: var(--text-secondary);
  font-weight: 500;
}

.hero-value {
  font-size: 42px;
  font-weight: 800;
  letter-spacing: -1px;
  margin: var(--space-2) 0 var(--space-5) 0;
  background: var(--brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-stats {
  display: flex;
  align-items: center;
  gap: var(--space-5);
}

.hero-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hs-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.hs-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.hero-divider {
  width: 1px;
  height: 36px;
  background: var(--border-base);
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
}

.asset-detail-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  position: relative;
  overflow: hidden;
  transition: all var(--transition-base);
}

.asset-detail-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.adc-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  color: white;
  margin-bottom: var(--space-3);
}

.up .adc-icon { background: var(--color-up-gradient); }
.warning .adc-icon { background: linear-gradient(135deg, #ffa726, #ffb74d); }
.info .adc-icon { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }
.primary .adc-icon { background: var(--brand-gradient); }

.adc-meta {
  margin-bottom: var(--space-3);
}

.adc-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.adc-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin-top: 4px;
}

.adc-bar {
  height: 4px;
  background: var(--bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.adc-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 600ms;
}

.up-fill { background: var(--color-up-gradient); }
.warning-fill { background: linear-gradient(135deg, #ffa726, #ffb74d); }
.info-fill { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }
.primary-fill { background: var(--brand-gradient); }

.adc-percent {
  font-size: 11px;
  color: var(--text-secondary);
}

.info-section {
  padding: var(--space-5);
}

.info-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: var(--space-4);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-4);
}

.info-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.info-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}

.up-dot { background: var(--color-up); }
.warning-dot { background: var(--color-warning); }
.info-dot-color { background: var(--color-info); }
.primary-dot { background: var(--brand-primary); }

.info-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.info-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

@media (max-width: 1100px) {
  .hero-content { grid-template-columns: 1fr; }
  .cards-grid { grid-template-columns: repeat(2, 1fr); }
  .info-grid { grid-template-columns: 1fr; }
}
</style>
