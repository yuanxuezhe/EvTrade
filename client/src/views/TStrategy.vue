<template>
  <div class="t-strategy-view fade-in-up">
    <div class="placeholder-card">
      <el-icon :size="64" class="placeholder-icon"><MagicStick /></el-icon>
      <h2 class="placeholder-title">做T策略</h2>
      <p class="placeholder-desc">敬请期待</p>
    </div>
  </div>
</template>

<script setup>
import { MagicStick } from '@element-plus/icons-vue'
</script>

<style scoped>
.t-strategy-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}

.placeholder-card {
  text-align: center;
  padding: var(--space-8);
}

.placeholder-icon {
  color: var(--text-placeholder);
}

.placeholder-title {
  margin: var(--space-4) 0 var(--space-2);
  font-size: 24px;
  color: var(--text-primary);
  font-weight: 600;
}

.placeholder-desc {
  color: var(--text-secondary);
  font-size: 14px;
}
</style>
