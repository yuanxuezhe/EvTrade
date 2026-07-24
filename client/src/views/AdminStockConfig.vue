<!--
  AdminStockConfig.vue — 证券信息 (admin-only)
  v25 stocks-cache-and-short-name: 表格分页走后端 + 编辑弹窗用 autocomplete
  v98 行内编辑: 取消弹窗, 直接在表格行内编辑除 stock_code 外所有字段

  - 查询:stocks 表列表(后端分页 page/page_size/total,服务端筛选 sector/keyword/is_t0_able)
  - 修改:行内编辑 → 保存 → PATCH /api/stocks/{code}
  - 添加: 弹窗 dialog (新增需要填 stock_code, 不能行内)
  - cache(全量)首次 onMounted 拉,autocomplete 用

  字段精简历史:
    v22: 11 字段编辑(行业/市场/上市日期/总股本/流通股本/总市值/PE/PB/简介 等)
    v23: 5 字段编辑(名称/板块/回转标志/最小买入数量/买卖单位)
    v25: 6 字段编辑(+short_name 拼音首字母)
    v46+: short_name 完全由后端自动生成 (前端列隐藏 + 无表单字段)
    v98: +stktype +scale + 行内编辑
-->
<template>
  <div class="admin-stock-config fade-in-up">
    <section class="stats-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">证券信息</h3>
            <p class="panel-sub">
              查询与编辑 stocks 表（行内编辑 + 全量缓存 + 真分页）
              <span v-if="store.cacheLoaded" class="cache-status">
                · 全量缓存 {{ store.cache.length }} 条
              </span>
              <span v-else-if="store.cacheLoading" class="cache-status">
                · 全量缓存加载中 {{ Math.round(store.cacheProgress * 100) }}%
              </span>
            </p>
          </div>
          <el-button :icon="Refresh" :loading="store.loading" @click="onRefresh">
            刷新
          </el-button>
          <el-button
            :icon="Refresh"
            :loading="store.cacheLoading"
            @click="onSyncCache"
          >
            同步缓存
          </el-button>
          <el-button type="primary" @click="onCreateOpen">
            添加证券
          </el-button>
        </div>

        <!-- 筛选条 -->
        <div class="filter-row">
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

        <!-- 表格: 行内编辑 -->
        <el-table
          :data="rows"
          stripe
          border
          v-loading="store.loading"
          height="calc(100vh - 380px)"
          empty-text="无数据"
          style="margin-top: 12px"
        >
          <el-table-column prop="stock_code" label="代码" width="110" />

          <el-table-column prop="stock_name" label="名称" min-width="90" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="!row._editing">{{ row.stock_name }}</span>
              <el-input v-else v-model="row._draft.stock_name" size="small" maxlength="64" />
            </template>
          </el-table-column>

          <el-table-column prop="sector" label="板块" min-width="90" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="!row._editing">{{ row.sector || '-' }}</span>
              <el-input v-else v-model="row._draft.sector" size="small" maxlength="64" />
            </template>
          </el-table-column>

          <el-table-column label="回转" width="100" align="center">
            <template #default="{ row }">
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
          </el-table-column>

          <el-table-column prop="min_buy_qty" label="最小买入" width="110" align="right">
            <template #default="{ row }">
              <span v-if="!row._editing" class="text-mono">{{ row.min_buy_qty ?? 100 }}</span>
              <el-input-number v-else v-model="row._draft.min_buy_qty" :min="1" size="small" controls-position="right" style="width: 100%" />
            </template>
          </el-table-column>

          <el-table-column prop="trade_unit" label="单位" width="90" align="right">
            <template #default="{ row }">
              <span v-if="!row._editing" class="text-mono">{{ row.trade_unit ?? 1 }}</span>
              <el-input-number v-else v-model="row._draft.trade_unit" :min="1" size="small" controls-position="right" style="width: 100%" />
            </template>
          </el-table-column>

          <el-table-column label="类型" width="90" align="center">
            <template #default="{ row }">
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
          </el-table-column>

          <el-table-column label="精度" width="80" align="center">
            <template #default="{ row }">
              <span v-if="!row._editing" class="text-mono">{{ row.scale ?? 2 }}</span>
              <el-input-number v-else v-model="row._draft.scale" :min="0" :max="6" size="small" controls-position="right" style="width: 100%" />
            </template>
          </el-table-column>

          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <template v-if="!row._editing">
                <el-button size="small" link type="primary" @click="startEdit(row)">
                  编辑
                </el-button>
              </template>
              <template v-else>
                <el-button size="small" type="primary" @click="commitEdit(row)">保存</el-button>
                <el-button size="small" @click="cancelEdit(row)">取消</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination">
          <el-pagination
            v-model:current-page="store.page"
            v-model:page-size="store.pageSize"
            :total="store.total"
            :page-sizes="[20, 50, 100, 200]"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="(p) => store.setPage(p)"
            @size-change="(sz) => store.setPageSize(sz)"
          />
        </div>
      </div>
    </section>

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

const store = useStocksStore()

// 筛选
const filters = reactive({ keyword: '', sector: '', is_t0_able: null })

// 板块下拉
const sectorOptions = computed(() => {
  const set = new Set()
  for (const s of store.pageRows) {
    if (s.sector) set.add(s.sector)
  }
  return [...set].sort()
})

// ==================== 行内编辑状态 ====================
// rows = pageRows 每个挂载 _editing / _draft
const rows = ref([])

// watch pageRows 变化时注入 _editing/_draft
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
  // 收集有变化的字段
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
    // 更新 row 数据
    Object.assign(row, updated)
    row._editing = false
    row._draft = {}
    // 同步 store cache + IDB
    store.upsertLocal(updated)
    ElMessage.success('保存成功')
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '保存失败'
    ElMessage.error(msg)
  }
}

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
    // 刷新当前页
    await onRefresh()
  } else {
    ElMessage.error(r.msg)
  }
}

async function onRefresh() {
  await store.fetchPage({
    sector: filters.sector || undefined,
    is_t0_able: filters.is_t0_able === null ? undefined : filters.is_t0_able
  })
  if (filters.keyword) {
    const kw = filters.keyword.trim().toLowerCase()
    store.pageRows = store.pageRows.filter((s) => {
      const code = (s.stock_code || '').toLowerCase()
      const name = (s.stock_name || '').toLowerCase()
      const short = (s.short_name || '').toLowerCase()
      return code.includes(kw) || name.includes(kw) || short.includes(kw)
    })
  }
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
.admin-stock-config { padding: 16px; }
.filter-row {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.cache-status {
  margin-left: 8px;
  color: var(--el-color-success, #67c23a);
  font-size: 12px;
}
.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.text-mono {
  font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
  font-size: 12px;
}
</style>
