<template>
  <div class="stat-card" :class="[`accent-${accent}`, { clickable: clickable }]">
    <div class="stat-header">
      <div class="stat-icon">
        <el-icon :size="20">
          <component :is="iconComponent" />
        </el-icon>
      </div>
      <div class="stat-label">{{ label }}</div>
    </div>

    <div class="stat-value-row">
      <span class="stat-value text-mono">
        <span v-if="prefix" class="stat-prefix">{{ prefix }}</span>{{ formattedValue }}
      </span>
      <span v-if="trend !== null && trend !== undefined" class="stat-trend" :class="trendClass">
        <el-icon :size="12">
          <CaretTop v-if="trend > 0" />
          <CaretBottom v-else-if="trend < 0" />
          <Minus v-else />
        </el-icon>
        {{ Math.abs(trend).toFixed(2) }}%
      </span>
    </div>

    <div v-if="sublabel" class="stat-sublabel">{{ sublabel }}</div>

    <div v-if="$slots.extra" class="stat-extra">
      <slot name="extra" />
    </div>

    <div class="stat-bg-decoration"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  Wallet, Money, DataAnalysis, TrendCharts, Box, PieChart,
  CaretTop, CaretBottom, Minus
} from '@element-plus/icons-vue'
import { formatMoney } from '../utils/format'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], required: true },
  prefix: { type: String, default: '' },
  sublabel: { type: String, default: '' },
  trend: { type: Number, default: null },
  icon: { type: String, default: 'Wallet' },
  accent: { type: String, default: 'primary' }, // primary | up | down | warning | info
  clickable: { type: Boolean, default: false },
  formatter: { type: Function, default: null }
})

const iconMap = { Wallet, Money, DataAnalysis, TrendCharts, Box, PieChart }
const iconComponent = computed(() => iconMap[props.icon] || Wallet)

const formattedValue = computed(() => {
  if (props.formatter) return props.formatter(props.value)
  if (typeof props.value === 'number') return formatMoney(props.value)
  return props.value
})

const trendClass = computed(() => {
  if (props.trend > 0) return 'trend-up'
  if (props.trend < 0) return 'trend-down'
  return 'trend-flat'
})
</script>

<style scoped>
.stat-card {
  position: relative;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  overflow: hidden;
  transition: all var(--transition-base);
}

.stat-card.clickable {
  cursor: pointer;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--brand-primary);
}

.stat-bg-decoration {
  position: absolute;
  top: -40px;
  right: -40px;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  opacity: 0.08;
  pointer-events: none;
}

.accent-primary .stat-bg-decoration { background: var(--brand-gradient); }
.accent-up .stat-bg-decoration { background: var(--color-up-gradient); }
.accent-down .stat-bg-decoration { background: var(--color-down-gradient); }
.accent-warning .stat-bg-decoration { background: linear-gradient(135deg, #ffa726, #ffb74d); }
.accent-info .stat-bg-decoration { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.stat-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.stat-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  color: white;
}

.accent-primary .stat-icon { background: var(--brand-gradient); box-shadow: 0 4px 12px rgba(79, 124, 255, 0.3); }
.accent-up .stat-icon { background: var(--color-up-gradient); box-shadow: 0 4px 12px rgba(245, 71, 93, 0.3); }
.accent-down .stat-icon { background: var(--color-down-gradient); box-shadow: 0 4px 12px rgba(22, 181, 114, 0.3); }
.accent-warning .stat-icon { background: linear-gradient(135deg, #ffa726, #ffb74d); box-shadow: 0 4px 12px rgba(255, 167, 38, 0.3); }
.accent-info .stat-icon { background: linear-gradient(135deg, #5fa8ff, #82b9ff); box-shadow: 0 4px 12px rgba(95, 168, 255, 0.3); }

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.stat-value-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.5px;
}

.stat-prefix {
  font-size: 16px;
  color: var(--text-secondary);
  margin-right: 2px;
}

.stat-trend {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: var(--radius-xs);
}

.trend-up {
  color: var(--color-up);
  background: var(--color-up-bg);
}

.trend-down {
  color: var(--color-down);
  background: var(--color-down-bg);
}

.trend-flat {
  color: #000;            /* v114.1: 用户口径 0 = 黑色 */
  background: transparent; /* v114.1: 0 状态无背景色 (保持原卡片背景) */
}

.stat-sublabel {
  margin-top: var(--space-2);
  font-size: 12px;
  color: var(--text-secondary);
}

.stat-extra {
  margin-top: var(--space-3);
}
</style>
