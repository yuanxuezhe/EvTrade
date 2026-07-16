<!--
  T0TaskDetail.vue — T0Task 详情视图（v18 change t0-task-management）

  Props:
    taskId (Number) — 当前查看的 task id（从路由 query 传）

  数据：
    - detail (Object) — task 实体 + summary（task_net_volume / position_vol / realized_pnl）
    - stats  (Object) — summary + daily + by_stock

  Emits:
    back() — 返回列表（外层路由 back）

  行为：
    - 详情展示：基础信息 + summary + daily 每日明细表 + by_stock 单券聚合
    - 三个操作按钮：配平建议 / 一键平仓 / 归档
-->
<template>
  <div class="t0-task-detail" v-loading="loading">
    <div class="ttd-header">
      <el-button link @click="$emit('back')">← 返回列表</el-button>
      <span class="ttd-title">
        T0 任务 #{{ taskId }}
        <el-tag :type="statusTagType(detail?.status)" size="small" style="margin-left: 8px">
          {{ statusLabel(detail?.status) }}
        </el-tag>
      </span>
      <div class="ttd-ops">
        <el-button v-if="detail?.status === 'active'" size="small" type="danger" @click="onClose">一键平仓</el-button>
        <el-button v-if="detail?.status !== 'archived'" size="small" type="danger" plain @click="onArchive">归档</el-button>
      </div>
    </div>

    <!-- 基本信息卡片 -->
    <el-card v-if="detail" class="ttd-base" shadow="hover">
      <div class="ttd-base-grid">
        <div class="field">
          <span class="label">股票代码</span>
          <span class="value text-mono">{{ detail.stock_code }}</span>
        </div>
        <div class="field">
          <span class="label">底仓量</span>
          <span class="value text-mono">{{ detail.base_volume }}</span>
        </div>
        <div class="field">
          <span class="label">目标开仓量</span>
          <span class="value text-mono">{{ detail.target_volume }}</span>
        </div>
        <div class="field">
          <span class="label">配平目标 (base+target)</span>
          <span class="value text-mono">
            <b>{{ detail.base_volume + detail.target_volume }}</b>
          </span>
        </div>
        <div class="field">
          <span class="label">配平系数</span>
          <span class="value text-mono">{{ detail.coefficient }}</span>
        </div>
        <div class="field">
          <span class="label">创建交易日</span>
          <span class="value text-mono">{{ detail.created_trd_date }}</span>
        </div>
        <div class="field" v-if="detail.note">
          <span class="label">备注</span>
          <span class="value">{{ detail.note }}</span>
        </div>
      </div>
    </el-card>

    <!-- summary -->
    <el-card v-if="detail?.summary" class="ttd-summary" shadow="hover">
      <template #header>汇总统计</template>
      <div class="summary-grid">
        <StatCard title="task 净开仓" :value="detail.summary.task_net_volume ?? 0" suffix="股" />
        <StatCard title="当前持仓" :value="detail.summary.position_vol ?? 0" suffix="股" />
        <StatCard title="已实现盈亏" :value="formatMoney(detail.summary.realized_pnl)" suffix="¥" :class="pnlClass(detail.summary.realized_pnl)" />
        <StatCard title="未实现盈亏" :value="formatMoney(detail.summary.unrealized_pnl)" suffix="¥" />
        <StatCard title="交易天数" :value="detail.summary.trading_days ?? 0" suffix="天" />
        <StatCard title="胜率" :value="((detail.summary.win_rate ?? 0) * 100).toFixed(1) + '%'" />
        <StatCard title="手续费" :value="formatMoney(detail.summary.commission_total)" suffix="¥" />
        <StatCard title="印花税" :value="formatMoney(detail.summary.stamp_tax_total)" suffix="¥" />
      </div>
    </el-card>

    <!-- daily 明细 -->
    <el-card v-if="stats?.daily?.length" class="ttd-daily" shadow="hover">
      <template #header>每日明细</template>
      <el-table :data="stats.daily" size="small" stripe>
        <el-table-column prop="trd_date" label="交易日" width="100" />
        <el-table-column prop="buy_vol" label="买入量" width="100" />
        <el-table-column prop="sell_vol" label="卖出量" width="100" />
        <el-table-column prop="buy_amt" label="买入额" width="100">
          <template #default="{ row }">¥{{ formatMoney(row.buy_amt) }}</template>
        </el-table-column>
        <el-table-column prop="sell_amt" label="卖出额" width="100">
          <template #default="{ row }">¥{{ formatMoney(row.sell_amt) }}</template>
        </el-table-column>
        <el-table-column prop="realized_pnl" label="已实现" width="100">
          <template #default="{ row }">
            <span :class="pnlClass(row.realized_pnl)">¥{{ formatMoney(row.realized_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_count" label="笔数" width="100" />
        <el-table-column prop="cum_pnl" label="累计盈亏" width="100">
          <template #default="{ row }">
            <span :class="pnlClass(row.cum_pnl)">¥{{ formatMoney(row.cum_pnl) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- by_stock -->
    <el-card v-if="stats?.by_stock?.length" class="ttd-bystock" shadow="hover">
      <template #header>单券聚合</template>
      <el-table :data="stats.by_stock" size="small" stripe>
        <el-table-column prop="stock_code" label="股票代码" width="100" />
        <el-table-column label="名称" width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-secondary">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="realized_pnl" label="已实现" width="100">
          <template #default="{ row }">
            <span :class="pnlClass(row.realized_pnl)">¥{{ formatMoney(row.realized_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unrealized_pnl" label="未实现" width="100">
          <template #default="{ row }">
            <span :class="pnlClass(row.unrealized_pnl)">¥{{ formatMoney(row.unrealized_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="task_count" label="task 数" width="100" />
        <el-table-column prop="trading_days" label="交易日" width="100" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useT0TasksStore } from '../../stores/t0_tasks'
import { stockName } from '../../utils/stockNames'
import StatCard from '../StatCard.vue'

const props = defineProps({
  taskId: { type: Number, required: true },
})
const emit = defineEmits(['back'])

const store = useT0TasksStore()
const detail = ref(null)
const stats = ref(null)
const loading = ref(false)

async function loadAll() {
  if (!props.taskId) return
  loading.value = true
  try {
    const [d, s] = await Promise.all([
      store.tasksById[props.taskId]
        ? Promise.resolve(store.tasksById[props.taskId])
        : import('../../api/t0_tasks').then(({ t0TasksApi }) => t0TasksApi.get(props.taskId)),
      import('../../api/t0_tasks').then(({ t0TasksApi }) => t0TasksApi.stats(props.taskId)),
    ])
    detail.value = d
    stats.value = s
  } finally {
    loading.value = false
  }
}

watch(() => props.taskId, () => loadAll(), { immediate: true })

async function onClose() {
  if (!confirm('确认一键平仓到 base_volume？将生成平仓委托。')) return
  try {
    const r = await store.closeTask(props.taskId)
    alert(`平仓委托已生成：${r.action} ${r.volume} 股`)
    await loadAll()
  } catch (e) {}
}
async function onArchive() {
  if (!confirm('确认归档该 task？归档后不再展示在主面板。')) return
  await store.archiveTask(props.taskId)
  await loadAll()
}

// helpers
function statusLabel(s) {
  return s === 'active' ? '活跃' : s === 'closed' ? '已平仓' : s === 'archived' ? '已归档' : s || '—'
}
function statusTagType(s) {
  if (s === 'active') return 'primary'
  if (s === 'closed') return 'info'
  return 'danger'
}
function pnlClass(v) {
  if (v > 0) return 'pnl-pos'
  if (v < 0) return 'pnl-neg'
  return ''
}
function formatMoney(v) { return (Number(v) || 0).toFixed(2) }
</script>

<style scoped>
.ttd-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.ttd-title {
  font-size: 16px;
  font-weight: 600;
  flex: 1;
}
.ttd-ops { display: flex; gap: 6px; }

.ttd-base-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px 24px;
}
.field {
  display: flex;
  flex-direction: column;
}
.label {
  font-size: 11px;
  color: var(--el-text-color-secondary, #909399);
  margin-bottom: 4px;
}
.value {
  font-size: 14px;
  font-weight: 500;
}

.ttd-summary,
.ttd-daily,
.ttd-bystock {
  margin-bottom: 14px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.pnl-pos { color: var(--el-color-success, #67c23a); }
.pnl-neg { color: var(--el-color-danger, #f56c6c); }
</style>
