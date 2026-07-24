<!--
  AdminStockConfig.vue — 证券信息 (admin-only)
  v25 stocks-cache-and-short-name: 表格分页走后端 + 编辑弹窗用 autocomplete

  - 查询:stocks 表列表(后端分页 page/page_size/total,服务端筛选 sector/keyword/is_t0_able)
  - 修改:点行 → 编辑弹窗 → PATCH /api/stocks/{code}
  - stock_code 输入:用 StockCodePicker 组件(三路筛选 code/name/short_name, 代码+名称左右拼接)
  - PATCH 时 store 同时刷新 cache + pageRows
  - cache(全量)首次 onMounted 拉 ~18s,autocomplete 用

  字段精简历史:
    v22: 11 字段编辑(行业/市场/上市日期/总股本/流通股本/总市值/PE/PB/简介 等)
    v23: 5 字段编辑(名称/板块/回转标志/最小买入数量/买卖单位)
    v25: 6 字段编辑(+short_name 拼音首字母)
    v46+: short_name 完全由后端自动生成 (前端列隐藏 + 无表单字段)
-->
<template>
  <div class="admin-stock-config fade-in-up">
    <!-- 顶部统计 -->
    <section class="stats-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">证券信息</h3>
            <p class="panel-sub">
              查询与编辑 stocks 表（v25 全量缓存 + 真分页 + 拼音首字母筛选）
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
          <!-- v90: 同步缓存按钮 (手动重刷 IDB, 用于其他页面改动后强制同步) -->
          <!-- v93: Sync icon 在 element-plus/icons-vue 不存在, 改用 Refresh -->
          <el-button
            :icon="Refresh"
            :loading="store.cacheLoading"
            @click="onSyncCache"
          >
            同步缓存
          </el-button>
          <!-- v46 stock-info-create: 添加证券按钮 (独立于编辑 dialog) -->
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

        <!-- 表格 -->
        <el-table
          :data="store.pageRows"
          stripe
          border
          v-loading="store.loading"
          height="calc(100vh - 380px)"
          empty-text="无数据"
          style="margin-top: 12px"
        >
          <el-table-column prop="stock_code" label="代码" min-width="100" />
          <el-table-column prop="stock_name" label="名称" min-width="100" />
          <el-table-column prop="sector" label="板块" min-width="100" show-overflow-tooltip />
          <el-table-column label="回转标志" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_t0_able" type="success" size="small">T+0</el-tag>
              <el-tag v-else type="info" size="small">T+1</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="min_buy_qty" label="最小买入数量" width="100" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ row.min_buy_qty ?? 100 }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="trade_unit" label="买卖单位" width="100" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ row.trade_unit ?? 1 }}</span>
            </template>
          </el-table-column>
          <!-- v46+ short-name-auto: 首字母列已隐藏 (后端自动生成, 前端无需展示) -->
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="onEdit(row)">
                编辑
              </el-button>
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

    <!-- 编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      title="编辑证券信息"
      width="640px"
      :close-on-click-modal="false"
      @closed="onDialogClosed"
    >
      <div v-if="store.editingCode" class="dialog-subtitle">
        编辑：
        <!-- v29: 切到 StockCodePicker (代码 + 名称左右拼接, blur 时未选自动清空) -->
        <StockCodePicker
          v-model="editingCodeRef"
          @select="onStockSelected"
          placeholder="搜索代码 / 名称 / 首字母"
          width="280px"
          style="margin-left: 8px"
        />
      </div>

      <el-form :model="store.editForm" label-width="110px" v-loading="store.editLoading">
        <el-form-item label="名称">
          <el-input v-model="store.editForm.stock_name" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="板块">
          <el-input v-model="store.editForm.sector" maxlength="64" placeholder="如：银行-国有大型银行" />
        </el-form-item>
        <!-- v46+ short-name-auto: 编辑对话框不显示 short_name 输入 (后端根据 stock_name 自动生成) -->
        <el-form-item label="回转标志">
          <el-switch
            v-model="store.editForm.is_t0_able"
            active-text="T+0"
            inactive-text="T+1"
            inline-prompt
            style="--el-switch-on-color: #13ce66; --el-switch-off-color: #ff4949"
          />
        </el-form-item>
        <el-form-item label="最小买入数量">
          <el-input-number
            v-model="store.editForm.min_buy_qty"
            :min="1"
            :step="100"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="买卖单位">
          <el-input-number
            v-model="store.editForm.trade_unit"
            :min="1"
            :step="1"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.editLoading" @click="onSave">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== 添加证券 dialog (v46 stock-info-create) ==================== -->
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
        <!-- v46+ short-name-auto: 添加对话框不显示 short_name 输入 (后端根据 stock_name 自动生成) -->
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
import StockCodePicker from '../components/StockCodePicker.vue'

const store = useStocksStore()

// 筛选（传给后端）
const filters = reactive({ keyword: '', sector: '', is_t0_able: null })

// 板块下拉（从当前 pageRows 抽，仅展示当前页可见的板块）
const sectorOptions = computed(() => {
  const set = new Set()
  for (const s of store.pageRows) {
    if (s.sector) set.add(s.sector)
  }
  return [...set].sort()
})

// 编辑弹窗
const dialogVisible = ref(false)
// 本地 v-model ref,绑定 autocomplete
const editingCodeRef = ref('')

async function onEdit(row) {
  const ok = await store.openEdit(row.stock_code)
  if (ok) {
    editingCodeRef.value = row.stock_code
    dialogVisible.value = true
  } else {
    ElMessage.error(`未找到 ${row.stock_code}`)
  }
}

async function onSave() {
  const res = await store.saveEdit()
  if (res.ok) {
    ElMessage.success(res.msg || '保存成功')
    dialogVisible.value = false
  } else {
    ElMessage.error(res.msg || '保存失败')
  }
}

function onDialogClosed() {
  store.closeEdit()
  editingCodeRef.value = ''
}

// ==================== 添加证券 (v46 stock-info-create) ====================

// dialog 可见性 + form ref
const createDialogVisible = ref(false)
const createFormRef = ref(null)

// form 数据模板(每次打开重置)
// v46+ short-name-auto: short_name 字段已移除 (后端自动生成)
const emptyCreateForm = () => ({
  stock_code: '',
  stock_name: '',
  sector: '',
  is_t0_able: false,
  min_buy_qty: 100,
  trade_unit: 1
})
const createForm = ref(emptyCreateForm())

// form 校验规则(与后端 Pydantic StockCreateRequest 对齐)
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
  min_buy_qty: [{ type: 'number', min: 1, message: '≥ 1', trigger: 'blur' }],
  trade_unit: [{ type: 'number', min: 1, message: '≥ 1', trigger: 'blur' }]
}

// 打开 dialog:重置 form + 清校验
function onCreateOpen() {
  createForm.value = emptyCreateForm()
  createFormRef.value?.clearValidate()
  createDialogVisible.value = true
}

// 提交
async function onCreateSave() {
  try {
    await createFormRef.value?.validate()
  } catch {
    return  // Element Plus 已显示行内错误
  }
  // 把空字符串转 null(后端 Optional 字段友好)
  const payload = {
    stock_code: createForm.value.stock_code.trim(),
    stock_name: createForm.value.stock_name.trim(),
    sector: createForm.value.sector.trim() || null,
    // v46+ short-name-auto: short_name 字段已移除 (后端根据 stock_name 自动生成)
    is_t0_able: createForm.value.is_t0_able,
    min_buy_qty: createForm.value.min_buy_qty,
    trade_unit: createForm.value.trade_unit
  }
  const r = await store.createStock(payload)
  if (r.ok) {
    ElMessage.success(`已添加 ${payload.stock_code} ${payload.stock_name}`)
    createDialogVisible.value = false
  } else {
    // 422 (字段校验) / 409 (重复) 都走这里
    ElMessage.error(r.msg)
  }
}

// autocomplete 选中候选时:刷新 editForm (拉新 stock 的详情)
function onStockSelected(stock) {
  if (stock && stock.stock_code) {
    store.openEdit(stock.stock_code)
  }
}

async function onRefresh() {
  // keyword 走前端 cache 筛选;sector/is_t0_able 走后端
  await store.fetchPage({
    sector: filters.sector || undefined,
    is_t0_able:
      filters.is_t0_able === null ? undefined : filters.is_t0_able
  })
  // keyword 客户端二次过滤(可选 - 后端已有 keyword 但只搜 code/name,前端 cache 还能搜 short_name)
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

// v90: 手动同步缓存 (从后端 /stocks/all 重刷 Map + IDB)
async function onSyncCache() {
  try {
    await store.refreshCache()
    ElMessage.success(`已同步 ${store.cache.length} 条证券信息`)
  } catch (e) {
    ElMessage.error('同步缓存失败: ' + (e?.message || e))
  }
}

onMounted(async () => {
  // 1. 拉首屏表格
  await store.fetchPage()
  // 2. 初始化 stocks cache (IDB 秒载, IDB 空则首次拉)
  if (!store.cacheLoaded && !store.cacheLoading) {
    store.initCache().catch((e) => {
      console.warn('[AdminStockConfig] cache 加载失败:', e)
    })
  }
})
</script>

<style scoped>
.admin-stock-config {
  padding: 16px;
}
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
.dialog-subtitle {
  font-size: 13px;
  color: var(--text-secondary, #909399);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-base, #ebeef5);
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