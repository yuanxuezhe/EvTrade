<!--
  AdminStockConfig.vue — 证券信息设置 (admin-only)
  v22 stock-info-editor
  - 查询:stocks 表列表(支持搜索 + 行业/市场筛选)
  - 修改:点行 → 编辑弹窗 → PATCH /api/stocks/{code}
  - 同步配置相关(cron/源/批量)在 /admin/sync 页面,本页面不涉及
-->
<template>
  <div class="admin-stock-config fade-in-up">
    <!-- 顶部统计 -->
    <section class="stats-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">证券信息</h3>
            <p class="panel-sub">查询与编辑 stocks 表（v22 stock-info-editor）</p>
          </div>
          <el-button :icon="Refresh" :loading="store.loading" @click="onRefresh">
            刷新
          </el-button>
        </div>

        <!-- 筛选条 -->
        <div class="filter-row">
          <el-input
            v-model="filters.keyword"
            placeholder="代码 / 名称搜索"
            clearable
            :prefix-icon="Search"
            style="width: 220px"
            @keyup.enter="onRefresh"
            @clear="onRefresh"
          />
          <el-select
            v-model="filters.industry"
            placeholder="行业"
            clearable
            style="width: 160px"
            @change="onRefresh"
          >
            <el-option
              v-for="i in industryOptions"
              :key="i"
              :label="i"
              :value="i"
            />
          </el-select>
          <el-select
            v-model="filters.market"
            placeholder="市场"
            clearable
            style="width: 120px"
            @change="onRefresh"
          >
            <el-option label="沪市 SH" value="SH" />
            <el-option label="深市 SZ" value="SZ" />
            <el-option label="北交所 BJ" value="BJ" />
          </el-select>
        </div>

        <!-- 表格 -->
        <el-table
          :data="pagedRows"
          stripe
          border
          v-loading="store.loading"
          height="calc(100vh - 380px)"
          empty-text="无数据"
          style="margin-top: 12px"
        >
          <el-table-column prop="stock_code" label="代码" min-width="110" />
          <el-table-column prop="stock_name" label="名称" min-width="110" />
          <el-table-column prop="market" label="市场" width="80" />
          <el-table-column prop="industry" label="行业" min-width="140" show-overflow-tooltip />
          <el-table-column prop="sector" label="板块" min-width="120" show-overflow-tooltip />
          <el-table-column prop="list_date" label="上市日期" width="120">
            <template #default="{ row }">
              <span class="text-mono">{{ formatDate(row.list_date) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="总市值" width="120" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ formatCap(row.market_cap) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="onEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="filteredRows.length"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next, jumper"
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
        <span class="text-mono">{{ store.editingCode }}</span>
      </div>

      <el-form :model="store.editForm" label-width="100px" v-loading="store.editLoading">
        <el-form-item label="名称">
          <el-input v-model="store.editForm.stock_name" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="store.editForm.industry" maxlength="64" />
        </el-form-item>
        <el-form-item label="板块">
          <el-input v-model="store.editForm.sector" maxlength="64" />
        </el-form-item>
        <el-form-item label="市场">
          <el-select v-model="store.editForm.market" placeholder="选择市场" style="width: 100%">
            <el-option label="沪市 SH" value="SH" />
            <el-option label="深市 SZ" value="SZ" />
            <el-option label="北交所 BJ" value="BJ" />
          </el-select>
        </el-form-item>
        <el-form-item label="上市日期">
          <el-input
            v-model="store.editForm.list_date"
            placeholder="YYYY-MM-DD 或 ISO datetime"
          />
        </el-form-item>
        <el-form-item label="总股本">
          <el-input-number
            v-model="store.editForm.total_share"
            :min="0"
            :step="10000"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="流通股本">
          <el-input-number
            v-model="store.editForm.float_share"
            :min="0"
            :step="10000"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="总市值">
          <el-input-number
            v-model="store.editForm.market_cap"
            :min="0"
            :precision="2"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="市盈率">
          <el-input-number
            v-model="store.editForm.pe_ratio"
            :precision="4"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="市净率">
          <el-input-number
            v-model="store.editForm.pb_ratio"
            :precision="4"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="公司简介">
          <el-input
            v-model="store.editForm.intro"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import { useStocksStore } from '../stores/stocks'

const store = useStocksStore()

// 筛选
const filters = reactive({ keyword: '', industry: '', market: '' })

// 分页
const page = ref(1)
const pageSize = ref(20)

// 行业下拉（从当前列表里抽）
const industryOptions = computed(() => {
  const set = new Set()
  for (const s of store.list) {
    if (s.industry) set.add(s.industry)
  }
  return [...set].sort()
})

// 客户端搜索 + 行业/市场过滤（后端只支持 industry/market 精确匹配）
const filteredRows = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  return store.list.filter((s) => {
    if (filters.industry && s.industry !== filters.industry) return false
    if (filters.market && s.market !== filters.market) return false
    if (kw) {
      const blob = `${s.stock_code || ''} ${s.stock_name || ''}`.toLowerCase()
      if (!blob.includes(kw)) return false
    }
    return true
  })
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

// 编辑弹窗
const dialogVisible = ref(false)

async function onEdit(row) {
  const ok = await store.openEdit(row.stock_code)
  if (ok) dialogVisible.value = true
  else ElMessage.error(`未找到 ${row.stock_code}`)
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
}

async function onRefresh() {
  await store.fetchList({ limit: 1000 })
}

// 格式化
function formatDate(s) {
  if (!s) return '—'
  // 后端返 ISO 字符串,只取前 10 位日期部分
  return String(s).slice(0, 10)
}
function formatCap(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)} 万`
  return n.toFixed(2)
}

onMounted(onRefresh)
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