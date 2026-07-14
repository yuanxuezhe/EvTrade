<!--
  CachePositions.vue — 持仓表 (admin 调试 + 调平)

  数据源：useHoldingsStore().positions (v8 单一源架构)

  v12 新增：每行可点"调平"按钮 → 弹 dialog → api.adjustPosition
    - 调平仅改 vol / avl_vol（cost_price / last_vol 不动）
    - 服务端把 synced_from 改 "manual"；下次 do_reconcile 会覆盖
    - 成功后用响应里的新 PositionOut 替换本行 Pinia 数据
-->
<template>
  <div class="cache-positions-view fade-in-up">
    <!-- 概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">行数</div>
        <div class="pill-value text-mono">{{ positions.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">Key Field</div>
        <div class="pill-value text-mono">stock_code</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">Data Source</div>
        <div class="pill-value text-mono">Pinia</div>
      </div>
    </section>

    <!-- 工具栏 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filterText"
          placeholder="搜索任意字段"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
        />
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table
        :data="filteredRows"
        stripe
        border
        height="calc(100vh - 360px)"
        empty-text="数据为空 (Pinia 内存)"
      >
        <el-table-column prop="stock_code" label="股票代码" min-width="100" show-overflow-tooltip />
        <el-table-column label="股票名称" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-secondary">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_vol" label="期初" min-width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avl_vol" label="可用" min-width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="vol" label="总持仓" min-width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cost_price" label="成本价" min-width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.cost_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="market_value" label="市值" min-width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.market_value) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="synced_at" label="同步时间" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.synced_at || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="synced_from" label="来源" min-width="100">
          <template #default="{ row }">
            <el-tag v-if="row.synced_from === 'manual'" type="warning" size="small">manual</el-tag>
            <el-tag v-else-if="row.synced_from" size="small">{{ row.synced_from }}</el-tag>
            <span v-else class="text-secondary">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openAdjust(row)">调平</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 调平 dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="`调平 ${adjustForm.stock_code || ''}`"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form :model="adjustForm" label-width="120px">
        <el-form-item label="股票代码">
          <el-input v-model="adjustForm.stock_code" disabled />
        </el-form-item>
        <el-form-item label="当前 vol">
          <span class="text-mono">{{ formatNumber(currentRow.vol) }}</span>
        </el-form-item>
        <el-form-item label="当前 avl_vol">
          <span class="text-mono">{{ formatNumber(currentRow.avl_vol) }}</span>
        </el-form-item>
        <el-form-item label="delta_vol (可选)">
          <el-input-number
            v-model="adjustForm.delta_vol"
            :controls="false"
            :precision="0"
            placeholder="整数, 负数=减"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="delta_avl_vol (可选)">
          <el-input-number
            v-model="adjustForm.delta_avl_vol"
            :controls="false"
            :precision="0"
            placeholder="整数, 负数=减"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="原因 (仅入log)">
          <el-input
            v-model="adjustForm.reason"
            type="textarea"
            :rows="2"
            :maxlength="255"
            show-word-limit
            placeholder="例如: 期权行权 / 银证转账补录"
          />
        </el-form-item>
        <el-alert
          v-if="!isAtLeastOneDelta"
          title="delta_vol / delta_avl_vol 至少传一个"
          type="warning" :closable="false" show-icon
          style="margin-top: 4px"
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary" :loading="saving"
          :disabled="!isAtLeastOneDelta"
          @click="onSubmit"
        >
          提交
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { useHoldingsStore } from '../stores/holdings'
import { api } from '../api'
import { formatMoney, formatNumber } from '../utils/format'
import { stockName } from '../utils/stockNames'

const holdingsStore = useHoldingsStore()
const positions = computed(() => holdingsStore.positions)

const filterText = ref('')
const filteredRows = computed(() => {
  if (!filterText.value) return positions.value
  const k = filterText.value.toLowerCase()
  return positions.value.filter((r) =>
    Object.values(r).some((v) => String(v).toLowerCase().includes(k))
  )
})

// 调平 dialog 状态
const dialogVisible = ref(false)
const saving = ref(false)
const currentRow = ref({})  // 备份当前行的 vol / avl_vol（dialog 只读展示）
const adjustForm = reactive({
  stock_code: '',
  delta_vol: null,
  delta_avl_vol: null,
  reason: ''
})

// 至少传一个 delta
const isAtLeastOneDelta = computed(() => {
  return adjustForm.delta_vol !== null || adjustForm.delta_avl_vol !== null
})

function _emptyAdjustForm() {
  return {
    stock_code: '',
    delta_vol: null,
    delta_avl_vol: null,
    reason: ''
  }
}

function openAdjust(row) {
  currentRow.value = { vol: row.vol, avl_vol: row.avl_vol }
  Object.assign(adjustForm, _emptyAdjustForm(), { stock_code: row.stock_code })
  dialogVisible.value = true
}

async function onSubmit() {
  if (!isAtLeastOneDelta.value) {
    ElMessage.warning('delta_vol / delta_avl_vol 至少传一个')
    return
  }
  saving.value = true
  try {
    const payload = {
      deltaVol: adjustForm.delta_vol ?? undefined,
      deltaAvlVol: adjustForm.delta_avl_vol ?? undefined,
      reason: adjustForm.reason || undefined
    }
    const resp = await api.adjustPosition(adjustForm.stock_code, payload)
    // 服务端返 {code: 0, msg, position: PositionOut}
    const newPos = resp?.position
    if (newPos) {
      // 用响应里的新行替换本行 Pinia 引用
      const idx = positions.value.findIndex((r) => r.stock_code === adjustForm.stock_code)
      if (idx >= 0) {
        positions.value.splice(idx, 1, newPos)
      }
      ElMessage.success(
        `调平成功: vol ${currentRow.value.vol} → ${newPos.vol}, ` +
        `avl_vol ${currentRow.value.avl_vol} → ${newPos.avl_vol}`
      )
    } else {
      ElMessage.success('调平成功')
    }
    dialogVisible.value = false
  } catch (e) {
    // 错误已由 axios 拦截器统一弹 ElMessage.error
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.cache-positions-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
}
.stat-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pill-label { font-size: 12px; color: var(--text-secondary); }
.pill-value { font-size: 18px; font-weight: 700; }

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  flex-wrap: wrap;
  gap: var(--space-3);
}

.text-mono {
  font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
}
.text-secondary { color: var(--text-secondary); }
</style>
