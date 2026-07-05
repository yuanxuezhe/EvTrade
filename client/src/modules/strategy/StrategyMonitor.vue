<!--
  StrategyMonitor.vue — 实时监控面板（task 11.8 拆文件保 ≤ 250 行）

  Props：
    strategy        - 完整策略对象（含嵌套 regimes/grids）
    currentTrdDate  - 当前交易日 8 位 YYYYMMDD

  拆分：
    - StrategyRegimeList.vue — regime collapse + grid 表格
    - StrategyAuditTable.vue — audit 倒序表格
-->
<template>
  <div class="strat-monitor" :data-el="'monitor-' + (strategy?.id || 'none')">
    <header class="sm-header">
      <div class="sm-title-row">
        <h3 class="sm-title">{{ strategy?.stock_code || '（未选择）' }}</h3>
        <el-tag
          v-if="strategy?.type"
          :type="TYPE_TAG_TYPE[strategy.type] || 'info'"
          size="small"
          :data-el="'monitor-type-' + strategy.type"
        >
          {{ TYPE_LABEL[strategy.type] || strategy.type }}
        </el-tag>
        <el-tag
          v-if="strategy?.status"
          :type="STATUS_TYPE[strategy.status] || 'info'"
          size="small"
          :data-el="'monitor-status-' + strategy.status"
        >
          {{ STATUS_LABEL[strategy.status] || strategy.status }}
        </el-tag>
        <span v-if="strategy?.note" class="sm-note">{{ strategy.note }}</span>
      </div>
      <div class="sm-control-row">
        <el-button
          v-if="canPause"
          size="small"
          type="warning"
          :loading="isPending('pause')"
          @click="onControl('pause')"
          data-el="monitor-pause"
        >
          暂停
        </el-button>
        <el-button
          v-if="canResume"
          size="small"
          type="success"
          :loading="isPending('resume')"
          @click="onControl('resume')"
          data-el="monitor-resume"
        >
          恢复
        </el-button>
        <el-button
          v-if="canStop"
          size="small"
          type="info"
          :loading="isPending('stop')"
          @click="onControl('stop')"
          data-el="monitor-stop"
        >
          停止
        </el-button>
        <el-button
          v-if="canClear"
          size="small"
          type="danger"
          :loading="isPending('clear_now')"
          @click="onControl('clear_now')"
          data-el="monitor-clear"
        >
          立即清仓
        </el-button>
      </div>
    </header>

    <section class="sm-section">
      <h4 class="sm-section-title">参数集 / 网格（{{ strategy?.regimes?.length || 0 }}）</h4>
      <StrategyRegimeList :regimes="strategy?.regimes || []" />
    </section>

    <section class="sm-section">
      <h4 class="sm-section-title">
        当日触发日志（{{ auditCount }}）
        <el-button
          link
          type="primary"
          size="small"
          :loading="auditLoading"
          @click="refreshAudit"
          data-el="monitor-audit-refresh"
        >
          刷新
        </el-button>
      </h4>
      <StrategyAuditTable :rows="auditRows" :loading="auditLoading" :max-rows="50" />
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useStrategyStore } from '../../stores/strategy'
import {
  useStrategy, STATUS_LABEL, STATUS_TYPE, TYPE_LABEL, TYPE_TAG_TYPE,
} from './composables/useStrategy'
import StrategyRegimeList from './StrategyRegimeList.vue'
import StrategyAuditTable from './StrategyAuditTable.vue'

const props = defineProps({
  strategy: { type: Object, default: null },
  currentTrdDate: { type: String, default: '' },
})

const store = useStrategyStore()
const { control } = useStrategy()

const canPause = computed(() => props.strategy?.status === 'active')
const canResume = computed(() => props.strategy?.status === 'paused')
const canStop = computed(() =>
  props.strategy?.status === 'active' || props.strategy?.status === 'paused'
)
const canClear = computed(() => canPause.value || canResume.value)

function isPending(action) {
  return store._isPending(`control:${props.strategy?.id}:${action}`)
}

async function onControl(action) {
  if (!props.strategy) return
  await control(props.strategy.id, action)
  if (action === 'clear_now') refreshAudit()
}

const auditRows = ref([])
const auditLoading = ref(false)
const auditCount = computed(() => auditRows.value.length)

async function refreshAudit() {
  if (!props.strategy?.id || !props.currentTrdDate) {
    auditRows.value = []
    return
  }
  auditLoading.value = true
  try {
    auditRows.value = await store.loadAudit(props.strategy.id, props.currentTrdDate)
  } catch (_) {
    auditRows.value = []
  } finally {
    auditLoading.value = false
  }
}

watch(
  () => [props.strategy?.id, props.currentTrdDate],
  () => refreshAudit(),
  { immediate: true },
)
</script>

<style scoped>
.strat-monitor {
  background: var(--bg-elevated);
  border-radius: var(--radius-base);
  padding: var(--space-4);
  border: 1px solid var(--border-base);
}
.sm-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
  flex-wrap: wrap;
  gap: var(--space-2);
}
.sm-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.sm-title {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}
.sm-note {
  color: var(--text-secondary);
  font-size: 13px;
  margin-left: var(--space-2);
}
.sm-control-row {
  display: flex;
  gap: var(--space-2);
}
.sm-section {
  margin-top: var(--space-3);
}
.sm-section-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 var(--space-2);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
</style>