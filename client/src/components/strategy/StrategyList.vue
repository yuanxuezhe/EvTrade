<!--
  StrategyList.vue — 策略列表（task 12 拆文件）

  Props：
    strategies  - Strategy[]
    selectedId  - 当前选中的 strategy id
  Emits：
    select(id)
-->
<template>
  <div class="strat-list" data-el="strategy-list">
    <el-empty
      v-if="!strategies?.length"
      :description="emptyDesc"
      :image-size="60"
    />
    <ul v-else class="sl-items">
      <li
        v-for="s in strategies"
        :key="s.id"
        class="sl-item"
        :class="{ active: s.id === selectedId }"
        :data-el="'strategy-list-item-' + s.id"
        @click="$emit('select', s.id)"
      >
        <div class="sl-row1">
          <span class="sl-code">{{ s.stock_code }}</span>
          <el-tag size="small" :type="STATUS_TYPE[s.status] || 'info'">
            {{ STATUS_LABEL[s.status] || s.status }}
          </el-tag>
        </div>
        <div class="sl-row2">
          <span class="sl-note">{{ s.note || '（无备注）' }}</span>
          <span class="sl-meta text-mono">V {{ s.base_volume }}</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { STATUS_LABEL, STATUS_TYPE } from '../../modules/strategy'

const props = defineProps({
  strategies: { type: Array, default: () => [] },
  selectedId: { type: [Number, null], default: null },
})
defineEmits(['select'])

const emptyDesc = computed(() => '暂无策略')
</script>

<style scoped>
.strat-list {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  background: var(--bg-base);
  max-height: 280px;
  overflow-y: auto;
}
.sl-items {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sl-item {
  padding: var(--space-2);
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background 100ms;
}
.sl-item:last-child {
  border-bottom: none;
}
.sl-item:hover {
  background: var(--bg-hover);
}
.sl-item.active {
  background: var(--brand-primary-soft, #ecf5ff);
  border-left: 3px solid var(--brand-primary);
}
.sl-row1 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}
.sl-code {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}
.sl-row2 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--space-1);
  font-size: 12px;
  color: var(--text-secondary);
}
.sl-note {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sl-meta {
  color: var(--text-placeholder);
  font-size: 11px;
}
</style>