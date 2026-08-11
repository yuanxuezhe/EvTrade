<!--
  StrategyOrderStatus.vue — 策略下单母单 状态徽章 (v126, 子组件)

  3 状态: stopped / running / closed
  颜色: stopped=info, running=success, closed=dark
-->
<template>
  <el-tag :type="type" effect="plain" size="small" :data-el="`so-status-${status}`">
    {{ label }}
  </el-tag>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: 'stopped' },
})

const type = computed(() => {
  if (props.status === 'running') return 'success'
  if (props.status === 'closed') return 'danger'
  return 'info'  // stopped 默认
})

const label = computed(() => {
  if (props.status === 'running') return '运行中'
  if (props.status === 'closed') return '已关闭'
  return '已停止'
})
</script>
