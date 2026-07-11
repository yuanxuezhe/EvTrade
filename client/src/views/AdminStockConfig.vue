<!--
  AdminStockConfig.vue — 证券信息设置 (admin-only)
  v23 slim-stocks-table
  - 查询:stocks 表列表(支持搜索 + 板块筛选)
  - 修改:点行 → 编辑弹窗 → PATCH /api/stocks/{code}
  - 同步配置相关(cron/源/批量)在 /admin/sync 页面,本页面不涉及

  字段精简历史:
    v22: 11 字段编辑(行业/市场/上市日期/总股本/流通股本/总市值/PE/PB/简介 等)
    v23: 5 字段编辑(名称/板块/回转标志/最小买入数量/买卖单位)
-->
<template>
  <div class="admin-stock-config fade-in-up">
    <!-- 顶部统计 -->
    <section class="stats-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">证券信息</h3>
            <p class="panel-sub">查询与编辑 stocks 表（v23 slim-stocks-table，6 字段精简版）</p>
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
          <el-table-column prop="sector" label="板块" min-width="140" show-overflow-tooltip />
          <el-table-column label="回转标志" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_t0_able" type="success" size="small">T+0</el-tag>
              <el-tag v-else type="info" size="small">T+1</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="min_buy_qty" label="最小买入数量" width="110" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ row.min_buy_qty ?? 100 }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="trade_unit" label="买卖单位" width="100" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ row.trade_unit ?? 1 }}</span>
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
      width="560px"
      :close-on-click-modal="false"
      @closed="onDialogClosed"
    >
      <div v-if="store.editingCode" class="dialog-subtitle">
        <span class="text-mono">{{ store.editingCode }}</span>
      </div>

      <el-form :model="store.editForm" label-width="110px" v-loading="store.editLoading">
        <el-form-item label="名称">
          <el-input v-model="store.editForm.stock_name" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="板块">
          <el-input v-model="store.editForm.sector" maxlength="64" placeholder="如：银行-国有大型银行" />
        </el-form-item>
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import { useStocksStore } from '../stores/stocks'

const store = useStocksStore()

// 筛选
const filters = reactive({ keyword: '', sector: '', is_t0_able: null })

// 分页
const page = ref(1)
const pageSize = ref(20)

// 板块下拉（从当前列表里抽）
const sectorOptions = computed(() => {
  const set = new Set()
  for (const s of store.list) {
    if (s.sector) set.add(s.sector)
  }
  return [...set].sort()
})

// 客户端搜索 + 板块/回转标志过滤（后端只支持 sector 精确匹配）
const filteredRows = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  return store.list.filter((s) => {
    if (filters.sector && s.sector !== filters.sector) return false
    if (filters.is_t0_able !== null && Boolean(s.is_t0_able) !== filters.is_t0_able) return false
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