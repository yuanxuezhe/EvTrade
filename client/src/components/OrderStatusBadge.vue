<template>
  <span class="order-status-badge" :class="['tone-' + tone, { pulse: pulse, 'size-sm': size === 'sm' }]">
    <span class="badge-dot"></span>
    <el-icon v-if="iconName" class="badge-icon" :size="iconSize">
      <component :is="iconComponent" />
    </el-icon>
    <span class="badge-label">{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import {
  STATUS_LABEL, STATUS_TONE, STATUS_ICON_NAME, STATUS_PULSE
} from '../utils/format'
import * as ElIcons from '@element-plus/icons-vue'

const props = defineProps({
  status: { type: String, default: '' },
  size: { type: String, default: 'sm' } // sm | md
})

const tone = computed(() => STATUS_TONE[props.status] || 'pending')
const label = computed(() => STATUS_LABEL[props.status] || props.status || '未知')
const pulse = computed(() => !!STATUS_PULSE[props.status])
const iconName = computed(() => STATUS_ICON_NAME[props.status] || 'QuestionFilled')
const iconComponent = computed(() => ElIcons[iconName.value] || ElIcons.QuestionFilled)
const iconSize = computed(() => (props.size === 'sm' ? 12 : 14))
</script>

<style scoped>
.order-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  white-space: nowrap;
  border: 1px solid transparent;
  transition: all var(--transition-fast);
  letter-spacing: 0.2px;
}

.size-sm {
  padding: 2px 8px;
  font-size: 12px;
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: currentColor;
  opacity: 0.85;
}

.badge-icon {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.badge-label {
  font-variant-numeric: tabular-nums;
}

/* Tone: pending —— 蓝色，等待/待报状态 */
.tone-pending {
  background: rgba(95, 168, 255, 0.10);
  color: #3a7bd5;
  border-color: rgba(95, 168, 255, 0.25);
}

/* Tone: working —— 橙色，部成/部成待撤等中间态 */
.tone-working {
  background: rgba(255, 167, 38, 0.12);
  color: #d97706;
  border-color: rgba(255, 167, 38, 0.30);
}

/* Tone: done —— 绿色，已成 */
.tone-done {
  background: rgba(22, 181, 114, 0.10);
  color: #16b572;
  border-color: rgba(22, 181, 114, 0.30);
}

/* Tone: terminal —— 灰色，已撤/废单/部撤等终止态 */
.tone-terminal {
  background: rgba(160, 174, 192, 0.12);
  color: #6b7785;
  border-color: rgba(160, 174, 192, 0.30);
}

/* Pulse 动画 —— 给仍可能变化的中间态 */
.pulse .badge-dot {
  animation: badge-pulse 1.6s ease-in-out infinite;
  box-shadow: 0 0 0 0 currentColor;
}

@keyframes badge-pulse {
  0% {
    box-shadow: 0 0 0 0 currentColor;
    opacity: 0.9;
  }
  70% {
    box-shadow: 0 0 0 5px transparent;
    opacity: 0.6;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
    opacity: 0.9;
  }
}
</style>
