# 持仓查询页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Vue3 前端新增一个"持仓查询"页面（路由 `/holdings`），表格 7 列与后端 `GET /api/positions` 字段一一对应，样式与 Orders.vue / Trades.vue 对齐，**不**改动现有 `/positions` 页面与后端。

**Architecture:** 新建一个视图组件 `client/src/views/Holdings.vue`，复用现有 `api.getPositions()`；在 `router/index.js` 注册 `/holdings` 路由；在 `Sidebar.vue` 菜单的"委托查询"和"成交查询"之间插入"持仓查询"项。视图内部用本地 `ref` 维护列表、关键字过滤、分页切片与 CSV 导出，**不**新增 Pinia store、**不**改后端。

**Tech Stack:** Vue 3 (Composition API)、Element Plus、`@element-plus/icons-vue`、Vite。无新增依赖。

---

## File Structure

| 文件 | 动作 | 职责 |
|------|------|------|
| `client/src/views/Holdings.vue` | **新建** | 持仓查询视图：筛选条 + 表格 + 分页 + CSV 导出 |
| `client/src/router/index.js` | **修改** | 动态 import + 注册 `/holdings` 路由 |
| `client/src/components/Sidebar.vue` | **修改** | 在 import 中加入 `Files` 图标；在 menuItems 数组插入"持仓查询"项 |

无新增 store、无后端改动、不动 `Position.vue` / `PositionTable.vue` / `position.js` / `api/index.js`。

---

## Task 1: 新建 Holdings.vue 视图

**Files:**
- Create: `client/src/views/Holdings.vue`

- [ ] **Step 1: 新建文件并写入完整内容**

创建 `client/src/views/Holdings.vue`，内容如下（与 `Orders.vue` / `Trades.vue` 风格一致）：

```vue
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
        <el-table-column prop="stock_name" label="股票名称" min-width="120">
          <template #default="{ row }">
            <span class="text-secondary">{{ row.stock_name || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="initial_position" label="期初" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.initial_position) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="today_buy" label="今日买入" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.today_buy) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="today_sell" label="今日卖出" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.today_sell) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="available" label="可用" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.available) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="total" label="总持仓" align="right" width="120">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.total) }}</span>
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
import { formatNumber } from '../utils/format'

const positions = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({ keyword: '' })

const filteredPositions = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  if (!kw) return positions.value
  return positions.value.filter(
    (p) =>
      (p.stock_code || '').toLowerCase().includes(kw) ||
      (p.stock_name || '').toLowerCase().includes(kw)
  )
})

const pagedPositions = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredPositions.value.slice(start, start + pageSize.value)
})

async function refresh() {
  loading.value = true
  try {
    positions.value = await api.getPositions()
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
  const header = ['股票代码', '股票名称', '期初', '今日买入', '今日卖出', '可用', '总持仓']
  const rows = filteredPositions.value.map((p) => [
    p.stock_code,
    p.stock_name || '',
    p.initial_position,
    p.today_buy,
    p.today_sell,
    p.available,
    p.total
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
```

- [ ] **Step 2: 提交**

```bash
git add client/src/views/Holdings.vue
git commit -m "feat: 新建持仓查询视图 Holdings.vue"
```

---

## Task 2: 注册 `/holdings` 路由

**Files:**
- Modify: `client/src/router/index.js:5-13`（动态 import 区块）与 `client/src/router/index.js:23`（routes 数组）

- [ ] **Step 1: 添加动态 import**

打开 `client/src/router/index.js`，在 `const Orders = () => import('../views/Orders.vue')` 之后插入：

```js
const Holdings = () => import('../views/Holdings.vue')
```

最终该区块应为：

```js
const Orders = () => import('../views/Orders.vue')
const Holdings = () => import('../views/Holdings.vue')
const Trades = () => import('../views/Trades.vue')
```

- [ ] **Step 2: 在 routes 数组中插入路由**

在 `routes` 数组中，定位到 `path: '/orders'` 这一行（title "委托查询"），紧接其下一行（`path: '/trades'` 之前）插入：

```js
{ path: '/holdings', name: 'Holdings', component: Holdings, meta: { title: '持仓查询' } },
```

最终顺序应为：`/` → `/positions` → `/trade` → `/orders` → `/holdings` → `/trades` → `/asset` → `/users` → `/profile` → 兜底重定向。

- [ ] **Step 3: 提交**

```bash
git add client/src/router/index.js
git commit -m "feat(router): 注册 /holdings 路由"
```

---

## Task 3: 在侧边栏插入"持仓查询"菜单项

**Files:**
- Modify: `client/src/components/Sidebar.vue:64-67`（icons import）与 `client/src/components/Sidebar.vue:79-92`（menuItems 数组）

- [ ] **Step 1: 在 icons import 中加入 `Files`**

打开 `client/src/components/Sidebar.vue`，定位到这一行：

```js
import {
  Odometer, Wallet, Money, DataAnalysis, List, Tickets,
  Fold, Expand, TrendCharts, UserFilled
} from '@element-plus/icons-vue'
```

改为：

```js
import {
  Odometer, Wallet, Money, DataAnalysis, List, Tickets,
  Fold, Expand, TrendCharts, UserFilled, Files
} from '@element-plus/icons-vue'
```

- [ ] **Step 2: 在 menuItems 数组插入菜单项**

定位到 `menuItems` 数组中：

```js
{
  path: '/orders',
  label: '委托查询',
  icon: List,
  badge: pendingCount.value > 0 ? pendingCount.value : null
},
{ path: '/trades', label: '成交查询', icon: Tickets },
```

在 `/orders` 之后、`/trades` 之前插入：

```js
{ path: '/orders', label: '委托查询', icon: List, badge: pendingCount.value > 0 ? pendingCount.value : null },
{ path: '/holdings', label: '持仓查询', icon: Files },
{ path: '/trades', label: '成交查询', icon: Tickets },
```

最终菜单顺序：`仪表盘 → 持仓管理 → 交易下单 → 委托查询 → 持仓查询 → 成交查询 → 账户资金 → 用户管理(仅 admin)`。

- [ ] **Step 3: 提交**

```bash
git add client/src/components/Sidebar.vue
git commit -m "feat(sidebar): 添加持仓查询菜单项"
```

---

## Task 4: 构建验证

**Files:** 无（仅运行命令）

- [ ] **Step 1: 在 client 目录执行生产构建**

```bash
cd client
npm run build
```

预期：构建成功，输出 `dist/` 目录，无 Vite/编译错误。常见报错若指向 `Holdings.vue` / `router/index.js` / `Sidebar.vue`，按错误提示修正。

- [ ] **Step 2: 启动 dev server 预览（可选）**

```bash
cd client
npm run dev
```

预期：Vite 启动并打印 `Local: http://localhost:5173/`。浏览器打开后：

1. 侧边栏出现"持仓查询"，位于"委托查询"和"成交查询"之间
2. 点击"持仓查询"，URL 变为 `/holdings`，表格渲染 7 列
3. 后端运行中时（`GET /api/positions` 返回非空），表格应展示接口返回的 7 个字段；字段为空时整列展示 `--` 或 `0`
4. 搜索框输入股票代码片段，列表按代码或名称过滤
5. 点击"刷新"重新拉取
6. 点击"导出 CSV"，下载 `持仓查询_YYYY-MM-DD.csv`，首行为 `股票代码,股票名称,期初,今日买入,今日卖出,可用,总持仓`
7. 分页器切换页码、改每页条数正常
8. 点击"持仓管理"（原 `/positions`）页面表现**与改动前一致**（顶部 4 个统计卡片、表格的"可用占比"列、抽屉明细等都还在）

- [ ] **Step 3: 关闭 dev server**

在终端按 `Ctrl+C` 停止 dev server。

---

## Self-Review

- **Spec 覆盖：**
  - §2 路由 `/holdings`、侧边栏位置 → Task 2 + Task 3 ✓
  - §2 表格 7 列与后端字段一一对应 → Task 1（7 个 el-table-column 直接绑定 stock_code/stock_name/initial_position/today_buy/today_sell/available/total）✓
  - §2 搜索 / 刷新 / CSV 导出 / 分页 → Task 1（filter-bar + exportCSV + el-pagination）✓
  - §2 不动 `/positions` 等 → 仅新建 Holdings.vue、改 router + sidebar；Task 4 验证第 8 条 ✓
  - §7 验证清单 8 条 → Task 4 Step 2 全部覆盖 ✓

- **占位符扫描：** 无 TBD / TODO / "类似 Task N" / 缺代码块的步骤

- **类型/方法一致性：**
  - `positions` / `filteredPositions` / `pagedPositions` / `page` / `pageSize` / `filters` / `refresh` / `resetFilters` / `exportCSV` / `loading` 在模板与 script 中名称一致
  - 模板中 `formatNumber` 来自 `utils/format`（与 Orders/Trades 一致）✓
  - `api.getPositions()` 来自 `api/index.js`（已存在）✓
  - 路由 `name: 'Holdings'` 与组件名一致；路径 `/holdings` 与 sidebar 路径一致 ✓

无内联修改。
