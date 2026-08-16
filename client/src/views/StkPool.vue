<!--
  StkPool.vue — 证券池管理 (add-stkpool-module change)
  布局: 左右分栏 (40% / 60%)
  - 左栏: 主表列表 + 新建池
  - 右栏: 当前池头部 + 添加股票 + 明细表

  行为契约:
  - onMounted 拉主表, 自动选中第一条
  - watch(selectedPoolId) 触发明细查询, cleanup 避免 race
  - 主表空 → 右栏 "暂无池, 请新建"
  - 添加股票用 StockCodePicker (v28 严格语义)
  - 明细行 stock_name 来自 useStocksStore.stockName(code)
  - 单一根 + dialog Teleport 到 body, 避免与 App.vue <Transition mode=out-in> 冲突
-->
<template>
  <div class="stkpool-page">
    <div class="stkpool-layout">
      <!-- 左栏: 主表 -->
      <aside class="stkpool-left">
        <header class="left-header">
          <h3>证券池</h3>
          <el-button type="primary" size="small" @click="onCreatePool">
            <el-icon><Plus /></el-icon>
            新建池
          </el-button>
        </header>
        <div class="left-table">
          <DataTableView
            :loading="loadingPools"
            :columns="poolColumns"
            :data="pools"
            row-key="id"
            highlight-current-row
            :current-row-key="selectedPoolId"
            :empty-description="'暂无池'"
            @row-click="onSelectPool"
          />
        </div>
      </aside>

      <!-- 右栏: 详情 -->
      <main class="stkpool-right">
        <template v-if="selectedPoolId">
          <header class="right-header">
            <div class="header-info">
              <span class="pool-name">{{ selectedPool?.name }}</span>
              <span class="pool-remark">{{ selectedPool?.remark || '（无备注）' }}</span>
            </div>
            <div class="header-actions">
              <el-button size="small" @click="onEditPool">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
              <el-button size="small" type="danger" @click="onDeletePool">
                <el-icon><Delete /></el-icon>删除
              </el-button>
            </div>
          </header>

          <div class="add-detail-bar">
            <el-button type="primary" @click="onOpenBatchAdd">
              <el-icon><Plus /></el-icon>批量添加
            </el-button>
            <span class="hint-text">支持搜索 / 多选 / 批量提交</span>
          </div>

          <div class="right-table">
            <DataTableView
              :loading="loadingDetail"
              :columns="detailColumns"
              :data="detail"
              row-key="stock_code"
              :empty-description="'暂无明细'"
            >
              <template #column-stock_code="{ row }">
                <span class="detail-line">
                  <span class="detail-code">{{ row.stock_code }}</span>
                  <span class="detail-name" v-t0-badge="row.stock_code">{{ getStockName(row.stock_code) }}</span>
                </span>
              </template>
              <template #column-action="{ row }">
                <el-button size="small" type="danger" @click="onRemoveDetail(row.stock_code)">
                  删除
                </el-button>
              </template>
            </DataTableView>
          </div>
        </template>

        <el-empty v-else description="暂无池，请新建" />
      </main>
    </div>

    <!-- 批量添加股票弹窗 — Teleport 到 body, 脱离父级 transition tree -->
    <Teleport to="body">
      <el-dialog
        v-model="batchAddVisible"
        title="批量添加股票到池"
        width="780px"
        :close-on-click-modal="false"
        append-to-body
        top="6vh"
      >
        <!-- 搜索栏 + 已有池内过滤 -->
        <div class="batch-toolbar">
          <el-input
            v-model="batchSearch"
            placeholder="搜索代码 / 名称 / 拼音首字母"
            clearable
            style="flex: 1; max-width: 360px;"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-checkbox v-model="batchHideInPool">仅显示未加入池内的</el-checkbox>
          <span class="selected-counter">
            已选 <b>{{ batchSelected.length }}</b> 只
            <el-button v-if="batchSelected.length > 0" size="small" text @click="batchSelected = []">
              清空
            </el-button>
          </span>
        </div>

        <!-- 已选 chips -->
        <div v-if="batchSelected.length > 0" class="selected-chips">
          <el-tag
            v-for="code in batchSelected.slice(0, 12)"
            :key="code"
            closable
            type="primary"
            size="small"
            @close="toggleSelect(code)"
            style="margin: 2px;"
          >
            {{ code }}
          </el-tag>
          <el-tag v-if="batchSelected.length > 12" type="info" size="small" style="margin: 2px;">
            +{{ batchSelected.length - 12 }} 更多
          </el-tag>
        </div>

        <!-- 股票列表 (复选) — lazy: 仅在 batchActivated 后才渲染数据 -->
        <DataTableView
          v-if="batchActivated"
          ref="batchTableRef"
          :loading="batchLoading"
          :columns="batchColumns"
          :data="batchFiltered"
          :row-key="row => row.stock_code"
          autoShell
          :height="'400'"
          :no-pagination="true"
          :empty-description="'无匹配股票'"
          style="margin-top: 12px;"
          @selection-change="onSelectionChange"
        >
          <template #column-stock_name="{ row }">
            <span v-t0-badge="row.stock_code">{{ row.stock_name }}</span>
          </template>
        </DataTableView>

        <!-- 弹窗刚打开时, 提示用户输入搜索词 -->
        <div v-else class="batch-placeholder">
          <el-empty
            :description="`请在上方搜索框输入股票代码、名称或拼音首字母开始 (${stocksStore.cache?.length || 0} 只股票已缓存)`"
            :image-size="100"
          />
        </div>

        <template #footer>
          <el-button @click="batchAddVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="batchSubmitting"
            :disabled="batchSelected.length === 0"
            @click="onSubmitBatchAdd"
          >
            添加 {{ batchSelected.length }} 只
          </el-button>
        </template>
      </el-dialog>
    </Teleport>

    <!-- 新建/编辑池弹窗 — Teleport 到 body, 脱离父级 transition tree -->
    <Teleport to="body">
      <el-dialog
        v-model="poolDialogVisible"
        :title="poolDialogMode === 'create' ? '新建池' : '编辑池'"
        width="480px"
        :close-on-click-modal="false"
        append-to-body
      >
        <el-form :model="poolForm" label-width="80px">
          <el-form-item label="池名" required>
            <el-input v-model="poolForm.name" maxlength="64" show-word-limit placeholder="请输入池名" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="poolForm.remark" type="textarea" :rows="3" maxlength="255" show-word-limit placeholder="可选" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="poolDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="poolDialogLoading" @click="onSubmitPoolForm">确认</el-button>
        </template>
      </el-dialog>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete, Search } from '@element-plus/icons-vue'
import { stkpoolApi } from '../api/stkpool'
import { useStocksStore } from '../stores/stocks'
import { COL } from '../utils/tableColumns'
import DataTableView from '../components/DataTableView.vue'

// ---- 列定义 (统一 DataTableView 模板) ----
// 左栏池列表
const poolColumns = [
  { key: 'id', label: 'ID', width: 56 },
  { key: 'name', label: '名称', minWidth: 120 },
  { key: 'remark', label: '备注', minWidth: 120 },
]

// 右栏池明细
const detailColumns = [
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'action', label: '操作', width: 100, align: 'center', fixed: 'right', sortable: false },
]

// 批量添加弹窗选股表
const batchColumns = [
  { type: 'selection', width: 48 },
  { key: 'stock_code', label: '代码', width: 120 },
  { key: 'stock_name', label: '名称', minWidth: 160 },
  { key: 'short_name', label: '拼音', width: 80 },
]

// ---- 状态 ----
const pools = ref([])
const loadingPools = ref(false)
const selectedPoolId = ref(null)
const detail = ref([])
const loadingDetail = ref(false)

// 池对话框
const poolDialogVisible = ref(false)
const poolDialogMode = ref('create')
const poolDialogLoading = ref(false)
const poolForm = ref({ name: '', remark: '' })

// ---- 批量添加股票弹窗 ----
const batchAddVisible = ref(false)
const batchSearch = ref('')
const batchHideInPool = ref(true)  // 默认隐藏已在池内的 (避免重复)
const batchSelected = ref([])      // 已选 stock_code 列表
const batchSubmitting = ref(false)
const batchTableRef = ref(null)

// 懒加载标记: 用户输入搜索词后才计算过滤结果, 避免 5529 行一次性渲染
const batchActivated = ref(false)

// 弹窗内全量股票列表 (来自 cache, 仅在 batchActivated 后才用)
const batchAllStocks = computed(() => {
  if (!batchActivated.value) return []
  return stocksStore.cache || []
})

// 当前池内已有股票 codes (用于"仅显示未加入池内")
const inPoolCodes = computed(() => new Set(detail.value.map(d => d.stock_code)))

// 过滤后的表格数据 (lazy: 仅 batchActivated=true 时才计算)
const batchFiltered = computed(() => {
  if (!batchActivated.value) return []
  let rows = batchAllStocks.value
  if (batchHideInPool.value) {
    rows = rows.filter(r => !inPoolCodes.value.has(r.stock_code))
  }
  const q = batchSearch.value.trim().toLowerCase()
  if (q) {
    rows = rows.filter(r =>
      (r.stock_code || '').toLowerCase().includes(q) ||
      (r.stock_name || '').toLowerCase().includes(q) ||
      (r.short_name || '').toLowerCase().includes(q)
    )
  }
  return rows
})

// 弹窗 loading (cache 未 loaded)
const batchLoading = computed(() => !stocksStore.cacheLoaded)

// ---- race-condition guard ----
// 路由切走时, 正在飞的 loadPools / loadDetail 不再 setState
let unmounted = false
onBeforeUnmount(() => { unmounted = true })

// ---- 派生 ----
const selectedPool = computed(() => pools.value.find(p => p.id === selectedPoolId.value) || null)

// ---- store ----
const stocksStore = useStocksStore()
function getStockName(code) {
  return stocksStore.stockName(code) || code
}

// 是否支持 T+0 (从 stocksStore.cache 读 is_t0_able) — 保留供批量弹窗用
function isT0Able(code) {
  const stock = stocksStore.cache?.find?.(s => s.stock_code === code)
  return !!stock?.is_t0_able
}

// 兼容 axios 错误 detail 的多种形态:
// - 字符串: "POOL_NOT_FOUND: id=999"
// - Pydantic 校验失败数组: [{loc, msg, type}, ...]
// - HTTPException dict: {code, msg}
function extractErrorMsg(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => `${(d.loc || []).join('.')}: ${d.msg || d.type || ''}`).join('; ')
  }
  if (detail && typeof detail === 'object') {
    return detail.msg || detail.code || JSON.stringify(detail)
  }
  return err?.message || '未知错误'
}

// ---- 初始化 ----
onMounted(async () => {
  await loadPools()
  if (unmounted) return
  // 默认选中第一行
  if (pools.value.length > 0) {
    selectedPoolId.value = pools.value[0].id
  }
})

// 切换池 → 拉明细 (watch 自动 cleanup, 无需手写)
watch(selectedPoolId, async (newId) => {
  if (newId) {
    await loadDetail(newId)
  } else {
    detail.value = []
  }
})

// ---- 加载主表 ----
async function loadPools() {
  loadingPools.value = true
  try {
    const rows = await stkpoolApi.list()
    if (unmounted) return
    pools.value = rows
  } catch (err) {
    if (unmounted) return
    ElMessage.error('加载池列表失败: ' + (extractErrorMsg(err)))
  } finally {
    if (!unmounted) loadingPools.value = false
  }
}

// ---- 加载明细 ----
async function loadDetail(poolId) {
  loadingDetail.value = true
  try {
    const rows = await stkpoolApi.detail(poolId)
    if (unmounted) return
    detail.value = rows
  } catch (err) {
    if (unmounted) return
    ElMessage.error('加载明细失败: ' + (extractErrorMsg(err)))
    detail.value = []
  } finally {
    if (!unmounted) loadingDetail.value = false
  }
}

// ---- 主表操作 ----
function onSelectPool(row) {
  selectedPoolId.value = row.id
}

function onCreatePool() {
  poolDialogMode.value = 'create'
  poolForm.value = { name: '', remark: '' }
  poolDialogVisible.value = true
}

function onEditPool() {
  if (!selectedPool.value) return
  poolDialogMode.value = 'edit'
  poolForm.value = {
    name: selectedPool.value.name,
    remark: selectedPool.value.remark,
  }
  poolDialogVisible.value = true
}

async function onSubmitPoolForm() {
  if (!poolForm.value.name.trim()) {
    ElMessage.warning('请输入池名')
    return
  }
  poolDialogLoading.value = true
  try {
    if (poolDialogMode.value === 'create') {
      const row = await stkpoolApi.create({
        name: poolForm.value.name.trim(),
        remark: poolForm.value.remark || '',
      })
      if (unmounted) return
      ElMessage.success('池创建成功')
      poolDialogVisible.value = false
      await loadPools()
      if (unmounted) return
      // 自动选中新创建的池
      selectedPoolId.value = row.id
    } else {
      await stkpoolApi.update(selectedPoolId.value, {
        name: poolForm.value.name.trim(),
        remark: poolForm.value.remark || '',
      })
      if (unmounted) return
      ElMessage.success('池已更新')
      poolDialogVisible.value = false
      await loadPools()
    }
  } catch (err) {
    if (unmounted) return
    ElMessage.error(extractErrorMsg(err))
  } finally {
    if (!unmounted) poolDialogLoading.value = false
  }
}

async function onDeletePool() {
  if (!selectedPool.value) return
  const pool = selectedPool.value
  try {
    await ElMessageBox.confirm(
      `将清除池 "${pool.name}" 下所有明细（${detail.value.length} 只），是否继续？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return  // 用户取消
  }
  try {
    await stkpoolApi.remove(pool.id)
    if (unmounted) return
    ElMessage.success('池已删除')
    // 重新拉主表
    await loadPools()
    if (unmounted) return
    // 自动选中第一条 (顺序保持)
    if (pools.value.length > 0) {
      selectedPoolId.value = pools.value[0].id
    } else {
      selectedPoolId.value = null
    }
  } catch (err) {
    if (unmounted) return
    ElMessage.error('删除失败: ' + (extractErrorMsg(err)))
  }
}

// ---- 明细操作 ----
function onOpenBatchAdd() {
  if (!stocksStore.cacheLoaded) {
    ElMessage.warning('股票缓存未加载, 请稍候再试')
    return
  }
  batchSearch.value = ''
  batchSelected.value = []
  batchHideInPool.value = true
  batchActivated.value = false   // 关键: 打开时不激活, 等用户输入搜索词
  batchAddVisible.value = true
  // nextTick 等 DOM 更新但不触发 reflow, 避免 setTimeout 阻塞 + forced reflow
  // el-table v-if + reserve-selection 组合, 打开即销毁重建, 无需手动 clearSelection
  nextTick(() => {
    if (batchTableRef.value) batchTableRef.value.clearSelection()
  })
}

// 用户输入搜索词后激活懒加载 (避免 5529 行一次性渲染)
watch(batchSearch, (q) => {
  if (q.trim() && !batchActivated.value) {
    batchActivated.value = true
  }
})

function onSelectionChange(rows) {
  batchSelected.value = rows.map(r => r.stock_code)
}

function toggleSelect(code) {
  batchSelected.value = batchSelected.value.filter(c => c !== code)
  // 同步 el-table 复选框
  const row = batchAllStocks.value.find(r => r.stock_code === code)
  if (row && batchTableRef.value) {
    batchTableRef.value.toggleRowSelection(row, false)
  }
}

async function onSubmitBatchAdd() {
  if (batchSelected.value.length === 0 || !selectedPoolId.value) return

  // 前端预校验: 后端 stock_codes 上限 10_000_000 字符 (约 100 万只股票)
  // 单次最多 50_000 只 (~ 实际股票池全量级, 防止恶意/误操作)
  const MAX_BATCH = 50_000
  if (batchSelected.value.length > MAX_BATCH) {
    ElMessage.warning(
      `单次最多添加 ${MAX_BATCH} 只, 当前选了 ${batchSelected.value.length} 只, 请分批`
    )
    return
  }
  const joined = batchSelected.value.join(',')
  if (joined.length > 10_000_000) {
    ElMessage.warning(
      `拼串长度 ${joined.length} 超过后端上限 10,000,000, 请减少选股数量`
    )
    return
  }

  batchSubmitting.value = true
  try {
    // v128: 单次请求批量提交, 后端 INSERT IGNORE 幂等
    const res = await stkpoolApi.detailAdd(selectedPoolId.value, batchSelected.value)
    if (unmounted) return
    const added = res?.added ?? batchSelected.value.length
    const skipped = res?.skipped ?? 0
    const skipMsg = skipped > 0 ? ` (${skipped} 只已在池内)` : ''
    ElMessage.success(`已添加 ${added} 只${skipMsg}`)
    batchAddVisible.value = false
    await loadDetail(selectedPoolId.value)
  } catch (err) {
    if (unmounted) return
    ElMessage.error('添加失败: ' + extractErrorMsg(err))
  } finally {
    if (!unmounted) batchSubmitting.value = false
  }
}

async function onRemoveDetail(stockCode) {
  try {
    await ElMessageBox.confirm(
      `确认从池中移除 ${stockCode}？`,
      '确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await stkpoolApi.detailRemove(selectedPoolId.value, stockCode)
    if (unmounted) return
    ElMessage.success('已移除')
    await loadDetail(selectedPoolId.value)
  } catch (err) {
    if (unmounted) return
    ElMessage.error('删除失败: ' + (extractErrorMsg(err)))
  }
}
</script>

<style scoped>
.stkpool-page {
  height: 100%;
}

.stkpool-layout {
  display: flex;
  height: 100%;
  gap: 16px;
  padding: 16px;
  box-sizing: border-box;
}

.stkpool-left {
  flex: 0 0 40%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.left-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
}

.left-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.left-table {
  flex: 1;
  overflow: auto;
}

.stkpool-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.right-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pool-name {
  font-size: 18px;
  font-weight: 600;
}

.pool-remark {
  font-size: 13px;
  color: #909399;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.add-detail-bar {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  align-items: center;
}

.add-detail-bar :deep(.scp-wrapper) {
  flex: 1;
}

.add-detail-bar .hint-text {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}

.batch-toolbar {
  display: flex;
  gap: 16px;
  align-items: center;
  padding-bottom: 8px;
}

.selected-counter {
  margin-left: auto;
  font-size: 13px;
  color: #606266;
}

.selected-counter b {
  color: #409eff;
  margin: 0 2px;
}

.selected-chips {
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  flex-wrap: wrap;
}

.batch-placeholder {
  margin-top: 12px;
  padding: 32px 16px;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  text-align: center;
}

.right-table {
  flex: 1;
  overflow: auto;
  padding: 0 16px 16px;
}

.detail-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.detail-code {
  font-family: 'SF Mono', Consolas, Monaco, monospace;
  font-weight: 600;
  color: #303133;
}

.detail-name {
  color: #606266;
}

@media (max-width: 900px) {
  .stkpool-layout {
    flex-direction: column;
  }
  .stkpool-left {
    flex: 0 0 40%;
  }
}
</style>