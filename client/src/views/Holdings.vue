<template>
  <div class="holdings-view fade-in-up">
    <!-- 筛选 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索股票代码或名称"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
        />
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
        <el-button :icon="Download" @click="exportCSV" :disabled="filteredPositions.length === 0">
          导出 CSV
        </el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table :data="pagedPositions" v-loading="loading" style="width: 100%">
        <el-table-column prop="stock_code" label="股票代码" width="120">
          <template #default="{ row }">
            <span class="stock-code">{{ row.stock_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_vol" label="期初持仓" align="right" min-width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.last_vol) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="持仓量" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="available" label="可用" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.available) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cost" label="成本价" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.cost) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="market_value" label="市值" align="right" width="140">
          <template #default="{ row }">
            <span class="text-mono">{{ formatMoney(row.market_value) }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无持仓" :image-size="100" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredPositions.length"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import { api } from '../api'
import { formatNumber, formatMoney } from '../utils/format'

const positions = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({ keyword: '' })

const filteredPositions = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  if (!kw) return positions.value
  return positions.value.filter(
    (p) => (p.stock_code || '').toLowerCase().includes(kw)
  )
})

const pagedPositions = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredPositions.value.slice(start, start + pageSize.value)
})

async function refresh() {
  loading.value = true
  try {
    positions.value = await api.getHoldings()
  } catch {
    // 错误已由 axios 拦截器统一弹 ElMessage.error
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
}

function exportCSV() {
  const header = ['股票代码', '期初持仓', '持仓量', '可用', '成本价', '市值']
  const rows = filteredPositions.value.map((p) => [
    p.stock_code,
    p.last_vol,
    p.volume,
    p.available,
    p.cost,
    p.market_value
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `持仓查询_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}

onMounted(refresh)
</script>

<style scoped>
.holdings-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  flex-wrap: wrap;
  gap: var(--space-3);
}

.filter-left {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.filter-right {
  display: flex;
  gap: var(--space-2);
}

.stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
}

.pagination {
  padding: var(--space-3) var(--space-4);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--border-light);
}
</style>
