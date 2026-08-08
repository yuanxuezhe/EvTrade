<template>
  <div class="admin-stock-config fade-in-up" :style="rootStyle">
    <!-- 工具栏 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filters.keyword"
          placeholder="代码 / 名称搜索（前端 cache 模糊匹配）"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
          @keyup.enter="onRefresh"
          @clear="onRefresh"
        />
        <el-select
          v-model="filters.sector"
          placeholder="板块"
          clearable
          style="width: 200px"
          @change="onRefresh"
        >
          <el-option
            v-for="s in sectorOptions"
            :key="s"
            :label="s"
            :value="s"
          />
        </el-select>
        <el-select
          v-model="filters.is_t0_able"
          placeholder="回转标志"
          clearable
          style="width: 140px"
          @change="onRefresh"
        >
          <el-option label="支持 T+0" :value="true" />
          <el-option label="不支持 T+0" :value="false" />
        </el-select>
      </div>
      <div class="filter-right">
        <span v-if="store.cacheLoaded" class="cache-status">
          全量缓存 {{ store.cache.length }} 条
        </span>
        <span v-else-if="store.cacheLoading" class="cache-status">
          缓存加载中 {{ Math.round(store.cacheProgress * 100) }}%
        </span>
        <el-button :icon="Refresh" :loading="store.loading" @click="onRefresh">
          刷新
        </el-button>
        <el-button :icon="Refresh" :loading="store.cacheLoading" @click="onSyncCache">
          同步缓存
        </el-button>
        <el-button type="primary" @click="onCreateOpen">
          添加证券
        </el-button>
      </div>
    </div>

    <!-- 表格: DataTableView + 行内编辑 -->
    <div class="content-card table-wrap" v-loading="store.loading">
      <DataTableView
        :columns="stockColumns"
        :data="rows"
        :empty-description="'无数据'"
        :no-pagination="true"
      >
        <template #column-stock_code="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
        </template>

        <template #column-stock_name="{ row }">
          <span v-if="!row._editing">{{ row.stock_name }}</span>
          <el-input v-else v-model="row._draft.stock_name" size="small" maxlength="64" />
        </template>

        <template #column-sector="{ row }">
          <span v-if="!row._editing">{{ row.sector || '-' }}</span>
          <el-input v-else v-model="row._draft.sector" size="small" maxlength="64" />
        </template>

        <template #column-t0="{ row }">
          <template v-if="!row._editing">
            <el-tag v-if="row.is_t0_able" type="success" size="small">T+0</el-tag>
            <el-tag v-else type="info" size="small">T+1</el-tag>
          </template>
          <el-switch
            v-else
            v-model="row._draft.is_t0_able"
            active-text="T+0"
            inactive-text="T+1"
            inline-prompt
          />
        </template>

        <template #column-min_buy_qty="{ row }">
          <span v-if="!row._editing" class="text-mono">{{ row.min_buy_qty ?? 100 }}</span>
          <el-input-number v-else v-model="row._draft.min_buy_qty" :min="1" size="small" controls-position="right" style="width: 100%" />
        </template>

        <template #column-trade_unit="{ row }">
          <span v-if="!row._editing" class="text-mono">{{ row.trade_unit ?? 1 }}</span>
          <el-input-number v-else v-model="row._draft.trade_unit" :min="1" size="small" controls-position="right" style="width: 100%" />
        </template>

        <template #column-stktype="{ row }">
          <template v-if="!row._editing">
            <el-tag :type="row.stktype === 1 ? 'warning' : 'info'" size="small">
              {{ row.stktype === 1 ? 'ETF' : '股票' }}
            </el-tag>
          </template>
          <el-select v-else v-model="row._draft.stktype" size="small" style="width: 100%">
            <el-option label="股票" :value="0" />
            <el-option label="ETF" :value="1" />
          </el-select>
        </template>

        <template #column-scale="{ row }">
          <span v-if="!row._editing" class="text-mono">{{ row.scale ?? 2 }}</span>
          <el-input-number v-else v-model="row._draft.scale" :min="0" :max="6" size="small" controls-position="right" style="width: 100%" />
        </template>

        <template #column-action="{ row }">
          <template v-if="!row._editing">
            <el-button size="small" link type="primary" @click.stop="startEdit(row)">
              编辑
            </el-button>
          </template>
          <template v-else>
            <el-button size="small" type="primary" @click.stop="commitEdit(row)">保存</el-button>
            <el-button size="small" @click.stop="cancelEdit(row)">取消</el-button>
          </template>
        </template>
      </DataTableView>
      <!-- 后端分页 (真分页) -->
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="store.page"
          v-model:page-size="store.pageSize"
          :total="store.total"
          :page-sizes="[50, 100, 200, 500]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="(p) => store.setPage(p)"
          @size-change="(sz) => store.setPageSize(sz)"
        />
      </div>
    </div>

    <!-- ==================== 添加证券 dialog ==================== -->
    <el-dialog v-model="createDialogVisible" title="添加证券" width="520px" :close-on-click-modal="false">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-form-item label="证券代码" prop="stock_code">
          <el-input v-model="createForm.stock_code" placeholder="例如 600519.SH" maxlength="16" />
        </el-form-item>
        <el-form-item label="证券名称" prop="stock_name">
          <el-input v-model="createForm.stock_name" placeholder="例如 贵州茅台" maxlength="64" />
        </el-form-item>
        <el-form-item label="所属板块" prop="sector">
          <el-input v-model="createForm.sector" placeholder="可选,例如 消费" maxlength="64" />
        </el-form-item>
        <el-form-item label="T+0">
          <el-switch v-model="createForm.is_t0_able" />
          <span style="margin-left: 12px; color: #909399; font-size: 12px;">默认 false (T+1)</span>
        </el-form-item>
        <el-form-item label="最小买入">
          <el-input-number v-model="createForm.min_buy_qty" :min="1" :step="100" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px;">股</span>
        </el-form-item>
        <el-form-item label="买卖单位">
          <el-input-number v-model="createForm.trade_unit" :min="1" :step="1" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px;">手</span>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.stktype" style="width: 100%">
            <el-option label="股票 (0)" :value="0" />
            <el-option label="ETF (1)" :value="1" />
          </el-select>
        </el-form-item>
        <el-form-item label="价格精度">
          <el-input-number v-model="createForm.scale" :min="0" :max="6" :step="1" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px;">小数位 (默认 2)</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.createLoading" @click="onCreateSave">
          添加
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import { useStocksStore } from '../stores/stocks'
import { stocksApi } from '../api'
import DataTableView from '../components/DataTableView.vue'
import { COL } from '../utils/tableColumns'
import { useUiStore } from '../stores/ui'
const uiStore = useUiStore()

const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))

const store = useStocksStore()

// 筛选
const filters = reactive({ keyword: '', sector: '', is_t0_able: null })

// 板块下拉 — v113: 从全量 cache 拿所有 sector
const sectorOptions = computed(() => {
  const set = new Set()
  for (const s of store.cache || []) {
    if (s.sector) set.add(s.sector)
  }
  return [...set].sort()
})

// ==================== 行内编辑状态 ====================
const rows = ref([])

watch(
  () => store.pageRows,
  (newRows) => {
    rows.value = newRows.map((r) => ({
      ...r,
      _editing: false,
      _draft: {}
    }))
  },
  { immediate: true }
)

function startEdit(row) {
  row._editing = true
  row._draft = {
    stock_name: row.stock_name || '',
    sector: row.sector || '',
    is_t0_able: row.is_t0_able ?? false,
    min_buy_qty: row.min_buy_qty ?? 100,
    trade_unit: row.trade_unit ?? 1,
    stktype: row.stktype ?? 0,
    scale: row.scale ?? 2,
  }
}

function cancelEdit(row) {
  row._editing = false
  row._draft = {}
}

async function commitEdit(row) {
  const payload = {}
  const d = row._draft
  const fields = ['stock_name', 'sector', 'is_t0_able', 'min_buy_qty', 'trade_unit', 'stktype', 'scale']
  for (const k of fields) {
    const newVal = d[k]
    const oldVal = row[k]
    if (String(newVal) !== String(oldVal)) {
      if (newVal === '' || newVal === null || newVal === undefined) continue
      payload[k] = newVal
    }
  }
  if (Object.keys(payload).length === 0) {
    ElMessage.warning('没有修改任何字段')
    cancelEdit(row)
    return
  }
  try {
    const updated = await stocksApi.update(row.stock_code, payload)
    Object.assign(row, updated)
    row._editing = false
    row._draft = {}
    store.upsertLocal(updated)
    ElMessage.success('保存成功')
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '保存失败'
    ElMessage.error(msg)
  }
}

// ==================== 列定义 ====================
const stockColumns = [
  { key: 'stock_code', label: '代码', vBind: COL.STOCK_CODE },
  { key: 'stock_name', label: '名称', width: 120, sortable: false },
  { key: 'short_name', label: '简称', width: 90, sortable: false },
  { key: 'sector', label: '板块', width: 120, sortable: false },
  { key: 't0', label: '回转', width: 100, align: 'center', headerAlign: 'center', sortable: false },
  { key: 'min_buy_qty', label: '最小买入', vBind: COL.NUMBER },
  { key: 'trade_unit', label: '单位', vBind: COL.NUMBER },
  { key: 'stktype', label: '类型', width: 90, align: 'center', headerAlign: 'center', sortable: false },
  { key: 'scale', label: '精度', width: 80, align: 'center', headerAlign: 'center', sortable: false },
  { key: 'action', label: '操作', width: 130, fixed: 'right', align: 'center', sortable: false },
]

// ==================== 添加证券 ====================

const createDialogVisible = ref(false)
const createFormRef = ref(null)

const emptyCreateForm = () => ({
  stock_code: '',
  stock_name: '',
  sector: '',
  is_t0_able: false,
  min_buy_qty: 100,
  trade_unit: 1,
  stktype: 0,
  scale: 2
})
const createForm = ref(emptyCreateForm())

const createRules = {
  stock_code: [
    { required: true, message: '请输入证券代码', trigger: 'blur' },
    {
      pattern: /^\d{6}\.(SH|SZ|BJ)$/,
      message: '格式必须是 6 位数字 + .SH/.SZ/.BJ (例如 600519.SH)',
      trigger: 'blur'
    }
  ],
  stock_name: [
    { required: true, message: '请输入证券名称', trigger: 'blur' },
    { min: 1, max: 64, message: '长度 1-64 字符', trigger: 'blur' }
  ],
  sector: [{ max: 64, message: '最长 64 字符', trigger: 'blur' }],
  min_buy_qty: [{ type: 'number', min: 1, message: '\u2265 1', trigger: 'blur' }],
  trade_unit: [{ type: 'number', min: 1, message: '\u2265 1', trigger: 'blur' }],
  stktype: [{ type: 'number', min: 0, max: 1, message: '0 或 1', trigger: 'blur' }],
  scale: [{ type: 'number', min: 0, max: 6, message: '0-6', trigger: 'blur' }]
}

function onCreateOpen() {
  createForm.value = emptyCreateForm()
  createFormRef.value?.clearValidate()
  createDialogVisible.value = true
}

async function onCreateSave() {
  try {
    await createFormRef.value?.validate()
  } catch {
    return
  }
  const payload = {
    stock_code: createForm.value.stock_code.trim(),
    stock_name: createForm.value.stock_name.trim(),
    sector: createForm.value.sector.trim() || null,
    is_t0_able: createForm.value.is_t0_able,
    min_buy_qty: createForm.value.min_buy_qty,
    trade_unit: createForm.value.trade_unit,
    stktype: createForm.value.stktype,
    scale: createForm.value.scale
  }
  const r = await store.createStock(payload)
  if (r.ok) {
    ElMessage.success(`已添加 ${payload.stock_code} ${payload.stock_name}`)
    createDialogVisible.value = false
    await onRefresh()
  } else {
    ElMessage.error(r.msg)
  }
}

async function onRefresh() {
  if (filters.keyword) {
    const matches = store.searchCache(filters.keyword.trim(), 10000)
    const filtered = matches.filter((s) => {
      if (filters.sector && s.sector !== filters.sector) return false
      if (filters.is_t0_able != null && Boolean(s.is_t0_able) !== Boolean(filters.is_t0_able)) return false
      return true
    })
    store.pageRows = filtered
    store.total = filtered.length
    return
  }
  await store.fetchPage({
    sector: filters.sector || undefined,
    is_t0_able: filters.is_t0_able === null ? undefined : filters.is_t0_able
  })
}

async function onSyncCache() {
  try {
    await store.refreshCache()
    ElMessage.success(`已同步 ${store.cache.length} 条证券信息`)
  } catch (e) {
    ElMessage.error('同步缓存失败: ' + (e?.message || e))
  }
}

onMounted(async () => {
  await store.fetchPage()
  if (!store.cacheLoaded && !store.cacheLoading) {
    store.initCache().catch((e) => {
      console.warn('[AdminStockConfig] cache 加载失败:', e)
    })
  }
})
</script>

<style scoped>
.admin-stock-config { display: flex; flex-direction: column; gap: var(--space-4); height: calc(100% - var(--oplog-extra, 0px)); min-height: 0; overflow: hidden; }
.filter-bar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-3) var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.filter-left { display: flex; gap: var(--space-2); align-items: center; }
.filter-right { display: flex; gap: var(--space-2); align-items: center; }
.cache-status { color: var(--el-color-success, #67c23a); font-size: 12px; margin-right: var(--space-2); white-space: nowrap; }
.table-wrap { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }
.pagination-bar { display: flex; justify-content: flex-end; padding: var(--space-3) var(--space-4) var(--space-3); border-top: 1px solid var(--border-light, #ebeef5); flex-shrink: 0; }
.text-mono { font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace); }
.tp-stock-code { font-family: var(--font-mono); font-weight: 600; }
</style>
