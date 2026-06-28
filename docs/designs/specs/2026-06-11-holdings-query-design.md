# 持仓查询页面设计方案

## 1. 背景

项目内已有一个"持仓管理"页面（`/positions`，由 `Position.vue` + `PositionTable.vue` + `PositionDetail.vue` 组成），它在前端做了大量派生加工：

- 顶部 4 个统计卡片（持仓数 / 总持仓量 / 可用量 / 今日净变动）
- 表格多出"可用占比"派生列和"操作 → 明细"列
- 抽屉明细展示"做T收益"、"需买回"等派生指标，并组合委托/成交接口数据

业务方要求新增一个**精简版**持仓查询页面，只展示后端 `GET /api/positions` 直接返回的 7 个原始字段，样式与"委托查询"、"成交查询"对齐。

## 2. 目标

- 路由 `/holdings`，侧边栏菜单名"持仓查询"，插入在"委托查询"和"成交查询"之间
- 表格 7 列与后端字段一一对应，不做任何派生计算
- 提供搜索、刷新、CSV 导出、分页，与 Orders.vue / Trades.vue 风格一致
- 不改动现有 `/positions` 页面、`PositionTable.vue` 组件、`position` store、`server/api/positions.py`

## 3. 后端接口

复用现有接口，无后端改动：

```
GET /api/positions
```

响应 `list` 元素结构（`PositionResponse`）：

| 字段 | 类型 | 含义 |
|------|------|------|
| `stock_code` | string | 股票代码 |
| `stock_name` | string | 股票名称 |
| `initial_position` | int | 期初持仓量 |
| `today_buy` | int | 今日累计买入量 |
| `today_sell` | int | 今日累计卖出量 |
| `available` | int | 当前可用持仓量 |
| `total` | int | 当前总持仓量 |

`api/index.js` 中已有的 `api.getPositions()` 方法经 axios 拦截器解包后直接返回上述字段数组。

## 4. 前端改动

### 4.1 新建 `client/src/views/Holdings.vue`

布局结构（与 `Orders.vue` / `Trades.vue` 一致，**不含顶部统计卡片**）：

```
<div class="holdings-view fade-in-up">
  <!-- 筛选 -->
  <div class="content-card filter-bar">
    <div class="filter-left">
      <el-input v-model="filters.keyword" placeholder="搜索股票代码或名称" clearable :prefix-icon="Search" style="width: 240px" />
      <el-button @click="resetFilters">清空</el-button>
    </div>
    <div class="filter-right">
      <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
      <el-button :icon="Download" @click="exportCSV" :disabled="filteredPositions.length === 0">导出 CSV</el-button>
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
```

Script 行为（参照 `Orders.vue` / `Trades.vue`）：

- `positions = ref([])`，本地状态，不引入 store
- `loading = ref(false)`、`page = ref(1)`、`pageSize = ref(20)`
- `filters = reactive({ keyword: '' })`
- `onMounted(refresh)`，内部 `await api.getPositions()`
- `filteredPositions`：按 `keyword` 大小写不敏感匹配 `stock_code` 或 `stock_name`
- `pagedPositions`：对 `filteredPositions` 按 `page` / `pageSize` 切片
- `exportCSV()`：导出 `filteredPositions`，列头 `['股票代码', '股票名称', '期初', '今日买入', '今日卖出', '可用', '总持仓']`，文件名 `持仓查询_${YYYY-MM-DD}.csv`，加 `\ufeff` BOM 防 Excel 乱码

样式（与 Orders.vue / Trades.vue 类名一致）：

- `.holdings-view`：`flex column`、`gap: var(--space-5)`
- `.filter-bar`：flex space-between、`padding: var(--space-3) var(--space-4)`、可换行
- `.filter-left` / `.filter-right`：flex、`gap: var(--space-2)`
- `.stock-code`：`font-family: var(--font-mono); font-weight: 600`
- `.pagination`：`flex justify-end`、上边框

### 4.2 编辑 `client/src/router/index.js`

在 `routes` 数组中追加路由：

```js
const Holdings = () => import('../views/Holdings.vue')
```

```js
{ path: '/holdings', name: 'Holdings', component: Holdings, meta: { title: '持仓查询' } }
```

注意：

- 路径与现有 `/positions` 不冲突
- 路由 meta 不需要 `requiresTrader` / `requiresAdmin`（与 Orders 一致对所有登录用户开放）
- 标题 `持仓查询` 与现有"持仓管理"区分开

### 4.3 编辑 `client/src/components/Sidebar.vue`

新增 `Files` 图标 import（来自 `@element-plus/icons-vue`）：

```js
import { ..., Files, ... } from '@element-plus/icons-vue'
```

在 `menuItems` 数组的"委托查询"和"成交查询"之间插入：

```js
{ path: '/holdings', label: '持仓查询', icon: Files }
```

最终顺序：`仪表盘 → 持仓管理 → 交易下单 → 委托查询 → 持仓查询 → 成交查询 → 账户资金 → 用户管理(仅 admin)`。

## 5. 数据流

```
onMounted
   ↓
api.getPositions()           ← client/src/api/index.js
   ↓ (axios 拦截器解包 {code, msg, list} → 数组)
positions.value = result
   ↓
filteredPositions = positions 关键字过滤(stock_code/stock_name)
   ↓
pagedPositions = filteredPositions 按 page/pageSize 切片
   ↓
el-table 渲染 7 列
   ↓
el-pagination 翻页 / 刷新按钮 / CSV 导出
```

## 6. 错误处理

沿用 `Orders.vue` / `Trades.vue` 的策略，**不写 try/catch 业务错误**：

- `api.getPositions()` 内部走 axios 拦截器：RPC `code !== 0` 自动 `ElMessage.error(msg)` 并 reject；HTTP 401 由全局处理器跳登录
- 调用方在 `refresh()` 中只控制 `loading` 状态

## 7. 验证清单

实施完成后需在浏览器中逐一确认：

1. 访问 `/holdings`，表格渲染 7 列（股票代码 / 股票名称 / 期初 / 今日买入 / 今日卖出 / 可用 / 总持仓）
2. 任意一行的 7 个单元格与 `GET /api/positions` 接口返回的 `list[i]` 7 字段**完全一致**（不含派生列）
3. 搜索框输入"600"或股票名称片段，表格正确过滤
4. 刷新按钮触发 `api.getPositions()` 重新拉取
5. CSV 导出文件名为 `持仓查询_YYYY-MM-DD.csv`，首行为 7 列表头
6. 分页器切换页码、改变每页条数正常
7. 侧边栏"持仓查询"位于"委托查询"与"成交查询"之间
8. 现有 `/positions` 页面表现无变化

## 8. 不在本次范围内

- 顶部统计卡片（持仓数 / 期初总量等）
- "可用占比"等派生列
- 行点击查看委托/成交明细抽屉
- 后端接口 / 数据库 / RPC 改动
- 现有 `/positions` 路由、Position.vue、PositionTable.vue、position store 改动
- 权限模型调整（持仓查询对所有登录用户开放，与委托/成交一致）
