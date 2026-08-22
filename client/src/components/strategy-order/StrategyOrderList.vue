<!--
  StrategyOrderList.vue — 策略母单列表 (子组件)

  列表: task_id / 策略名 / 标的 / 状态徽章 / run_count / 子单数 / 操作按钮
  选中行联动子单面板 (emit 'select')
  操作: 启动 (stopped only) / 停止 (running only) / 关闭 (running 禁用)
-->
<template>
  <el-card shadow="never" class="so-list-card" data-el="so-list-card">
    <template #header>
      <div class="so-card-head">
        <span>策略母单</span>
        <span class="so-card-sub">{{ orders.length }} 个</span>
      </div>
    </template>
    <el-table
      :data="orders"
      v-loading="loading"
      size="small"
      border
      stripe
      highlight-current-row
      :row-key="(r) => r.id"
      :current-row-key="selectedId"
      empty-text="暂无母单, 从上方「策略下单」创建"
      data-el="so-list-table"
      @row-click="onRowClick"
    >
      <el-table-column label="task_id" prop="task_id" width="90" />
      <el-table-column label="策略名" prop="strategy_name" min-width="160">
        <template #default="{ row }">
          <span>{{ row.strategy_name || `#${row.strategy_id}` }}</span>
        </template>
      </el-table-column>
      <el-table-column label="标的" prop="stock_code" width="100" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <StrategyOrderStatus :status="row.status" />
        </template>
      </el-table-column>
      <el-table-column label="启动次数" prop="run_count" width="80" />
      <el-table-column label="子单数" prop="children_count" width="80" />
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'stopped'"
            size="small"
            type="primary"
            :loading="busy[`start_${row.id}`]"
            data-el="so-start-btn"
            @click.stop="onStart(row)"
          >
            启动
          </el-button>
          <el-button
            v-if="row.status === 'running'"
            size="small"
            type="warning"
            :loading="busy[`stop_${row.id}`]"
            data-el="so-stop-btn"
            @click.stop="onStop(row)"
          >
            停止
          </el-button>
          <el-button
            size="small"
            type="danger"
            :disabled="row.status === 'running'"
            :loading="busy[`close_${row.id}`]"
            data-el="so-close-btn"
            @click.stop="onClose(row)"
          >
            关闭
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { scriptStrategyApi } from '../../api/script_strategy'
import StrategyOrderStatus from './StrategyOrderStatus.vue'

const props = defineProps({
  orders: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  selectedId: { type: Number, default: null },
})
const emit = defineEmits(['select', 'refresh'])

const busy = reactive({})

async function onStart(row) {
  busy[`start_${row.id}`] = true
  try {
    await scriptStrategyApi.startStrategyOrder(row.id)
    ElMessage.success(`母单 #${row.task_id} 已启动`)
    emit('refresh')
  } catch (e) {
    ElMessage.error(`启动失败: ${e?.response?.data?.detail?.msg || e.message}`)
  } finally {
    busy[`start_${row.id}`] = false
  }
}

async function onStop(row) {
  busy[`stop_${row.id}`] = true
  try {
    await scriptStrategyApi.stopStrategyOrder(row.id)
    ElMessage.success(`母单 #${row.task_id} 已停止`)
    emit('refresh')
  } catch (e) {
    ElMessage.error(`停止失败: ${e?.response?.data?.detail?.msg || e.message}`)
  } finally {
    busy[`stop_${row.id}`] = false
  }
}

async function onClose(row) {
  try {
    await ElMessageBox.confirm(
      `确认关闭母单 #${row.task_id}? 关闭后不可再启动, 但保留历史子单审计。`,
      '关闭母单',
      { type: 'warning' },
    )
  } catch {
    return
  }
  busy[`close_${row.id}`] = true
  try {
    await scriptStrategyApi.closeStrategyOrder(row.id)
    ElMessage.success(`母单 #${row.task_id} 已关闭`)
    emit('refresh')
  } catch (e) {
    ElMessage.error(`关闭失败: ${e?.response?.data?.detail?.msg || e.message}`)
  } finally {
    busy[`close_${row.id}`] = false
  }
}

function onRowClick(row) {
  emit('select', row)
}
</script>
