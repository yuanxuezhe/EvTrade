<!--
  StrategyAuditTable.vue — audit 触发日志表格（task 11.8 拆文件保 ≤ 250 行）

  Props：
    rows    - AuditRecord[]（已按时间倒序）
    loading - 加载态
    maxRows - 渲染行数上限（默认 50）
-->
<template>
  <div class="audit-table" data-el="audit-table">
    <el-table
      :data="pagedRows"
      :show-overflow-tooltip="true"
      size="small"
      v-loading="loading"
      :max-height="320"
      stripe
      class="audit-el-table"
    >
      <el-table-column prop="created_at" label="时间" width="160">
        <template #default="{ row }">
          <span class="text-mono text-secondary">{{ formatTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="trigger_type" label="触发类型" width="160">
        <template #default="{ row }">
          <el-tag size="small" :type="triggerTypeColor(row.trigger_type)">
            {{ TRIGGER_LABEL[row.trigger_type] || row.trigger_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="regime_id" label="regime" width="80" align="right">
        <template #default="{ row }">
          <span v-if="row.regime_id" class="text-mono">#{{ row.regime_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="当前价" width="100" align="right">
        <template #default="{ row }">
          <span v-if="row.current_price != null" class="text-mono">
            {{ row.current_price.toFixed(3) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="持仓量" width="80" align="right">
        <template #default="{ row }">
          <span v-if="row.position_vol != null" class="text-mono">{{ row.position_vol }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="order_no" label="委托号" width="120">
        <template #default="{ row }">
          <span v-if="row.order_no" class="text-mono">{{ row.order_no }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="reject_reason" label="拒绝原因" min-width="160">
        <template #default="{ row }">
          <span v-if="row.reject_reason" class="audit-reject">{{ row.reject_reason }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无触发记录" :image-size="60" />
      </template>
    </el-table>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  maxRows: { type: Number, default: 50 },
})

const TRIGGER_LABEL = {
  grid_triggered: '网格触发',
  regime_changed: 'regime 切换',
  regime_cooldown: 'regime 冷却',
  control_pause: '手动暂停',
  control_resume: '手动恢复',
  control_stop: '手动停止',
  control_clear_now: '手动清仓',
  order_rejected: '委托被拒',
}

function triggerTypeColor(t) {
  if (t === 'regime_changed') return 'success'
  if (t === 'grid_triggered') return 'primary'
  if (t === 'regime_cooldown') return 'warning'
  if (t === 'order_rejected') return 'danger'
  if (t && t.startsWith('control_')) return 'info'
  return 'info'
}

function formatTime(s) {
  if (!s) return ''
  // created_at 是 ISO 字符串，截掉毫秒和时区尾巴便于对齐
  return String(s).replace('T', ' ').replace(/\.\d+Z?$/, '').replace('Z', '')
}

const pagedRows = computed(() => {
  const list = Array.isArray(props.rows) ? props.rows : []
  return list.slice(0, props.maxRows)
})
</script>

<style scoped>
.audit-table {
  width: 100%;
}
.audit-el-table {
  font-size: 12px;
}
.audit-reject {
  color: var(--color-down);
}
</style>