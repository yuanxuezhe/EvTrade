<!--
  CachePositions.vue — 缓存持仓查看 (IDB 读取, 调试用 + 调平)

  数据源: IDB (loadAllPositions)
  DataTableView 内部分页, 保留调平 dialog
-->
<template>
  <div class="cache-positions-view fade-in-up" :style="rootStyle">
    <!-- 工具栏 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="stockCode"
          placeholder="股票代码 (可选)"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
        />
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card table-wrap" v-loading="loading">
      <DataTableView
        :columns="positionColumns"
        :data="filteredResults"
        :default-sort="{ prop: 'vol', order: 'descending' }"
        :default-page-size="50"
        :empty-description="'无持仓数据'"
        @row-dblclick="(row) => { if (row.stock_code) stockCode.value = row.stock_code }"
      >
        <template #column-stock_code="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
          <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
        </template>
        <template #column-last_vol="{ row }">
          <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
        </template>
        <template #column-avl_vol="{ row }">
          <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
        </template>
        <template #column-vol="{ row }">
          <span class="text-mono">{{ formatNumber(row.vol) }}</span>
        </template>
        <template #column-cost_price="{ row }">
          <span class="text-mono">{{ formatPrice(row.cost_price, row.stock_code) }}</span>
        </template>
        <template #column-market_value="{ row }">
          <span class="text-mono">{{ formatMoney(row.market_value) }}</span>
        </template>
        <template #column-synced_from="{ row }">
          <el-tag v-if="row.synced_from === 'manual'" type="warning" size="small">manual</el-tag>
          <el-tag v-else-if="row.synced_from" size="small">{{ row.synced_from }}</el-tag>
          <span v-else class="text-secondary">-</span>
        </template>
        <template #column-synced_at="{ row }">
          <span class="text-mono text-secondary">{{ row.synced_at || '-' }}</span>
        </template>
        <template #column-action="{ row }">
          <el-button size="small" type="primary" plain @click="openAdjust(row)">调平</el-button>
        </template>
      </DataTableView>
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
            :controls="false" :precision="0"
            placeholder="整数, 负数=减"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="delta_avl_vol (可选)">
          <el-input-number
            v-model="adjustForm.delta_avl_vol"
            :controls="false" :precision="0"
            placeholder="整数, 负数=减"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="原因 (仅入log)">
          <el-input
            v-model="adjustForm.reason"
            type="textarea" :rows="2" :maxlength="255"
            show-word-limit
            placeholder="例如: 期权行权 / 银证转账补录"
          />
        </el-form-item>
        <el-alert v-if="!isAtLeastOneDelta"
                  title="delta_vol / delta_avl_vol 至少传一个"
                  type="warning" :closable="false" show-icon
                  style="margin-top: 4px" />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!isAtLeastOneDelta" @click="onSubmit">
          提交
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import DataTableView from '../components/DataTableView.vue'
import { api } from '../api'
import { formatMoney, formatNumber } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import { loadAllPositions } from '../stores/holdings_idb'
import { useUiStore } from '../stores/ui'

const uiStore = useUiStore()
const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))

const results = ref([])
const loading = ref(false)
const stockCode = ref('')

const filteredResults = computed(() => {
  if (!stockCode.value) return results.value
  const k = stockCode.value.toLowerCase()
  return results.value.filter((r) => String(r.stock_code).toLowerCase().includes(k))
})

onMounted(async () => {
  loading.value = true
  try {
    results.value = (await loadAllPositions()) || []
  } catch (e) { console.error('[CachePositions] IDB 加载失败:', e?.message || e); results.value = [] }
  finally { loading.value = false }
})

/* ---------- 调平 dialog 状态 ---------- */
const dialogVisible = ref(false)
const saving = ref(false)
const currentRow = ref({})
const adjustForm = reactive({ stock_code: '', delta_vol: null, delta_avl_vol: null, reason: '' })

const isAtLeastOneDelta = computed(() => adjustForm.delta_vol !== null || adjustForm.delta_avl_vol !== null)

function openAdjust(row) {
  currentRow.value = { vol: row.vol, avl_vol: row.avl_vol }
  Object.assign(adjustForm, { stock_code: row.stock_code, delta_vol: null, delta_avl_vol: null, reason: '' })
  dialogVisible.value = true
}

async function onSubmit() {
  if (!isAtLeastOneDelta.value) { ElMessage.warning('delta_vol / delta_avl_vol 至少传一个'); return }
  saving.value = true
  try {
    const payload = {
      deltaVol: adjustForm.delta_vol ?? undefined,
      deltaAvlVol: adjustForm.delta_avl_vol ?? undefined,
      reason: adjustForm.reason || undefined
    }
    const resp = await api.adjustPosition(adjustForm.stock_code, payload)
    const newPos = resp?.position
    if (newPos) {
      const idx = results.value.findIndex((r) => r.stock_code === adjustForm.stock_code)
      if (idx >= 0) results.value.splice(idx, 1, newPos)
      ElMessage.success(`调平成功: vol ${currentRow.value.vol} → ${newPos.vol}, avl_vol ${currentRow.value.avl_vol} → ${newPos.avl_vol}`)
    } else { ElMessage.success('调平成功') }
    dialogVisible.value = false
  } catch (e) { /* axios 拦截器已弹 error */ }
  finally { saving.value = false }
}

const positionColumns = [
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'last_vol', label: '期初', vBind: COL.NUMBER },
  { key: 'vol', label: '总持仓', vBind: COL.NUMBER },
  { key: 'avl_vol', label: '可用', vBind: COL.NUMBER },
  { key: 'cost_price', label: '成本价', vBind: COL.PRICE },
  { key: 'market_value', label: '市值', vBind: COL.MONEY },
  { key: 'synced_from', label: '来源', width: 100, sortable: false },
  { key: 'synced_at', label: '同步时间', vBind: COL.TIME },
  { key: 'action', label: '操作', width: 100, fixed: 'right', sortable: false },
]
</script>

<style scoped>
.cache-positions-view { display: flex; flex-direction: column; gap: var(--space-4); height: calc(100% - var(--oplog-extra, 0px)); min-height: 0; overflow: hidden; }
.filter-bar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-3) var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.filter-left { display: flex; gap: var(--space-2); align-items: center; }
.text-mono { font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace); }
.text-secondary { color: var(--text-secondary); }
.tp-stock-code { font-family: var(--font-mono); font-weight: 600; }
.table-wrap { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }
</style>
