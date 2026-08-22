<!--
  StrategyOrderDetail.vue — 策略母单元数据 (子组件)

  选中母单后展示元数据 (task_id / 策略名 / 标的 / 状态 / 启停时间 / 关闭时间 / 启动次数)
-->
<template>
  <div v-if="order" class="so-detail" data-el="so-detail">
    <div class="so-detail-row">
      <span class="so-detail-key">task_id</span>
      <span class="so-detail-val">{{ order.task_id }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">策略</span>
      <span class="so-detail-val">{{ order.strategy_name || `#${order.strategy_id}` }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">标的</span>
      <span class="so-detail-val">{{ order.stock_code }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">状态</span>
      <span class="so-detail-val"><StrategyOrderStatus :status="order.status" /></span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">启动次数</span>
      <span class="so-detail-val">{{ order.run_count || 0 }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">最近启动</span>
      <span class="so-detail-val">{{ order.last_started_at || '—' }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">最近停止</span>
      <span class="so-detail-val">{{ order.last_stopped_at || '—' }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">关闭时间</span>
      <span class="so-detail-val">{{ order.closed_at || '—' }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">active_task_id</span>
      <span class="so-detail-val">{{ order.active_task_id || '—' }}</span>
    </div>
    <div class="so-detail-row">
      <span class="so-detail-key">创建</span>
      <span class="so-detail-val">{{ order.created_at }}</span>
    </div>
  </div>
  <div v-else class="so-detail-empty" data-el="so-detail-empty">
    请选择左侧母单查看详情
  </div>
</template>

<script setup>
import StrategyOrderStatus from './StrategyOrderStatus.vue'

defineProps({
  order: { type: Object, default: null },
})
</script>

<style scoped>
.so-detail { display: flex; flex-direction: column; gap: 8px; }
.so-detail-row {
  display: flex; gap: 12px; align-items: baseline;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  padding-bottom: 4px;
}
.so-detail-key { width: 110px; color: var(--el-text-color-secondary); font-size: 13px; }
.so-detail-val { font-size: 13px; }
.so-detail-empty { color: var(--el-text-color-secondary); padding: 24px; text-align: center; }
</style>
