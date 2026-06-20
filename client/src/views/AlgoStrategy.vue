<template>
  <div class="algo-strategy-view fade-in-up">
    <div class="placeholder-card">
      <!-- 标题/描述由 AppHeader pageMeta 统一显示, 此处仅保留占位图标 -->
      <el-icon :size="64" class="placeholder-icon"><Cpu /></el-icon>
    </div>
  </div>
</template>

<script setup>
import { Cpu } from '@element-plus/icons-vue'
</script>

<style scoped>
.algo-strategy-view {
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
</style>
