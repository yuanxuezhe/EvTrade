## ADDED Requirements

### Requirement: StkPool.vue 左右布局（REQ-STKPOOL-FE-001）

The system SHALL 提供 `client/src/views/StkPool.vue` 视图，采用左右双栏布局：

- **左栏 (40% 宽度)**：主表列表 + "新建池"按钮
- **右栏 (60% 宽度)**：当前选中池的详情（池名/备注 + 明细表 + 添加股票）

#### Scenario: 整体布局

- **WHEN** user 导航到 `/stkpool`
- **THEN** `StkPool.vue` 渲染为 `.stkpool-layout` flex 容器
- **AND** 左栏 `.stkpool-left` 宽度 40%，含 `el-table` (主表) + 顶部 "+ 新建池" 按钮
- **AND** 右栏 `.stkpool-right` 宽度 60%，含头部（池名/备注）+ 添加股票 + `el-table` (明细)
- **AND** 响应式：视口 < 900px 时左/右栏 stack 垂直（CSS media query）

#### Scenario: 左栏主表渲染

- **WHEN** `pools` ref 包含 10 个池
- **THEN** el-table 渲染 10 行
- **AND** 每行显示 `id / name / remark` 三列
- **AND** 行高亮当前选中池（`highlight-current-row` + `currentRow` 绑定）
- **AND** 行点击 (`@row-click`) → 触发 `onSelect(row)` → 更新 `selectedPoolId`

#### Scenario: 右栏空状态

- **WHEN** `selectedPoolId` 为 null（主表为空或未加载）
- **THEN** 右栏渲染 `<el-empty description="暂无池，请新建" />`
- **AND** 头部（池名/备注）+ 明细表 MUST NOT 渲染

### Requirement: 默认选中第一条主表（REQ-STKPOOL-FE-002）

The system SHALL 在 `StkPool.vue` 页面加载时自动选中主表第一条，并触发对应明细查询。

#### Scenario: onMounted 自动选中

- **WHEN** user 访问 `/stkpool` 路由
- **THEN** `onMounted` hook 触发 `loadPools()`
- **AND** `loadPools` 调 `stkpoolApi.list()` 返回主表
- **AND** 若 `pools.value.length > 0` → `selectedPoolId.value = pools.value[0].id`
- **AND** `watch(selectedPoolId)` 自动触发 `loadDetail(selectedPoolId.value)`
- **AND** 右栏明细表渲染第一条池的明细

#### Scenario: 主表空时无默认选中

- **WHEN** `loadPools()` 返回 `pools = []`
- **THEN** `selectedPoolId.value` 保持 null
- **AND** 右栏显示 `el-empty` "暂无池，请新建"
- **AND** 不会触发 `loadDetail`（watch 不触发）

#### Scenario: 切换池刷新明细

- **WHEN** user 点击左栏主表第 3 行
- **THEN** `onSelect(row)` → `selectedPoolId.value = row.id`
- **AND** `watch(selectedPoolId)` 触发 `loadDetail(newId)`
- **AND** `loadDetail` 调 `stkpoolApi.detail(newId)` 拉新数据
- **AND** 右栏明细表替换为新池的明细

#### Scenario: 池删除后自动切下一条

- **WHEN** user 删除了当前选中的池（第 2 行）
- **THEN** `loadPools()` 重新拉主表（10 → 9 行）
- **AND** 自动选中第 2 行（原来第 3 行变成第 2 行）
- **AND** 右栏明细刷新

### Requirement: 批量添加股票（REQ-STKPOOL-FE-003）

The system SHALL 提供 `StkPool.vue` 右栏"批量添加"按钮，弹 `el-dialog` 支持**搜索 / 多选 / 批量提交**，避免逐个添加。

**对话框结构**：

- 顶部 toolbar：搜索框 + "仅显示未加入池内"勾选 + 已选计数
- 已选 chips 区：前 12 个 stock_code 显示为蓝色 tag，超过显示 `+N 更多`
- 主区域：`el-table` 多选（`type="selection"`，**移除 `:reserve-selection` 避免 forced reflow**），列 `代码 / 名称 / 拼音`
- 底部 footer：取消 + "添加 N 只"（N = 已选数）

**数据源**：`useStocksStore.cache`（5529 行内存全量股票），弹窗打开时必须 `cacheLoaded === true`，否则按钮禁用 + ElMessage 提示

#### Scenario: 打开批量添加弹窗（懒加载）

- **WHEN** user 点击右栏 "+ 批量添加" 按钮
- **AND** `stocksStore.cacheLoaded === true`
- **THEN** 弹 `el-dialog` 含 toolbar + chips + **el-empty 占位**（不渲染 el-table）
- **AND** `batchActivated = false`（懒加载标记）
- **AND** `batchAllStocks` computed 返 `[]`（避免 5529 行一次性渲染）
- **AND** `batchFiltered` computed 返 `[]`（不计算过滤）
- **AND** `batchSearch` 清空 + `batchSelected` 清空 + `batchHideInPool` 默认 true
- **AND** `setTimeout(clearSelection)` 等一帧清空旧选中状态

#### Scenario: 输入搜索词激活懒加载

- **WHEN** user 在搜索框输入任意非空字符
- **THEN** `watch(batchSearch)` 触发 `batchActivated = true`
- **AND** el-table `v-if` 渲染 + 显示过滤后的股票列表
- **AND** 占位 el-empty 自动隐藏

#### Scenario: 关闭弹窗重置

- **WHEN** user 关闭弹窗再次打开
- **THEN** `batchActivated = false`（在 `onOpenBatchAdd` 内重置）
- **AND** 弹窗回到占位状态
- **AND** 必须重新输入搜索词才显示股票列表

#### Scenario: cache 未加载时禁止打开

- **WHEN** user 点击 "+ 批量添加"
- **AND** `stocksStore.cacheLoaded === false`
- **THEN** MUST NOT 弹窗
- **AND** `ElMessage.warning('股票缓存未加载, 请稍候再试')`

#### Scenario: 搜索过滤

- **WHEN** user 在搜索框输入 "600519" 或 "茅台" 或 "GZMT"
- **THEN** `batchFiltered` computed 实时过滤 `batchAllStocks`
- **AND** 过滤规则：stock_code / stock_name / short_name 任一字段 `.toLowerCase().includes(q)`
- **AND** 大小写不敏感

#### Scenario: 多选 + chips 联动

- **WHEN** user 在 el-table 勾选 N 行
- **THEN** `onSelectionChange(rows)` → `batchSelected = rows.map(r => r.stock_code)`
- **AND** chips 区显示前 12 个 stock_code
- **AND** 已选计数实时更新
- **AND** 点 chip 的关闭按钮 → `toggleSelect(code)` → 同步 el-table 复选框状态

#### Scenario: 仅显示未加入池内（默认）

- **WHEN** `batchHideInPool === true`（默认）
- **THEN** `batchFiltered` 排除当前池已存在的 stock_code
- **AND** user 取消勾选 → 显示全部股票（含已在池内的）

#### Scenario: 批量提交（v128 单次请求）

- **WHEN** user 点击 "添加 N 只" 按钮
- **AND** `batchSelected.length > 0`
- **THEN** 前端**单次请求**：`stkpoolApi.detailAdd(poolId, batchSelected)` 内部 join 成 `stock_codes: "code1,code2,..."`
- **AND** 后端响应 201 + `{pool_id, added: N, skipped: M}`
- **AND** 前端 `ElMessage.success('已添加 N 只 (M 只已在池内)')`
- **AND** 关闭弹窗 + `loadDetail(selectedPoolId)` 刷新明细表
- **AND** 性能对比：旧循环 N 次请求 → 新单次请求（一次事务 INSERT IGNORE）

### Requirement: 明细行 stock_name 来自 useStocksStore.stockName（REQ-STKPOOL-FE-004）

The system SHALL 让 `StkPool.vue` 明细表的"名称"列从 `useStocksStore().stockName(code)` 内存缓存读取，不调后端。

#### Scenario: 名称从 store.stockName 读取

- **WHEN** 明细表渲染某行 `stock_code = '600519.SH'`
- **THEN** 模板调用 `getStockName('600519.SH')`
- **AND** 函数返回 `stocksStore.stockName('600519.SH') || '600519.SH'`
- **AND** store.stockName 实现：内部走 `cacheMap.get(code)?.stock_name`（Map O(1)）
- **AND** 若 cache 已 loaded（典型场景）→ 显示"贵州茅台"
- **AND** 若 cache 未 loaded（兜底）→ 显示 code 本身，不阻塞

#### Scenario: cache 加载时机

- **WHEN** user 第一次访问 `/stkpool`
- **THEN** 假设 `useStocksStore` 已在 AppHeader 或 Dashboard.vue 加载过
- **AND** 若未加载 → 显示 code 兜底
- **AND** MUST NOT 在 `StkPool.vue` 主动调 `stocksStore.load()`（避免副作用）

#### Scenario: 重命名后 cache 同步

- **WHEN** 管理员在 `AdminStockConfig` 改了 stock_code '600519.SH' 的 stock_name
- **AND** `useStocksStore` 刷新 cache
- **THEN** `StkPool.vue` 明细表名称列自动更新（响应式）

### Requirement: 菜单位置（REQ-STKPOOL-FE-005）

The system SHALL 将"证券池"作为**与"证券信息"同级别**的顶级菜单项，**不在**"证券信息"内嵌套为子菜单。`menuItems` 数组中"证券池"项紧跟"证券信息"之后。

#### Scenario: Sidebar 顶级项顺序

- **WHEN** `Sidebar.vue` 渲染 `menuItems` 数组
- **THEN** "证券信息" 顶级项（`/admin/stock-config`）之后紧跟"证券池"顶级项（`/stkpool`）
- **AND** 两者展示为**平级**（同级 el-menu-item），无嵌套关系
- **AND** MUST NOT 出现 `el-sub-menu` 包裹结构（决策修订）

#### Scenario: 点击顶级项跳转

- **WHEN** user 点击"证券池"顶级项
- **THEN** router 跳转 `/stkpool`（顶层路由，与 `/admin/stock-config` 同级）
- **AND** 直接打开 `StkPool.vue`
- **AND** URL MUST 显示 `/stkpool`（用户可分享 URL）

#### Scenario: 刷新高亮

- **WHEN** user 刷新页面（路径 `/stkpool`）
- **THEN** Sidebar 自动高亮"证券池"顶级项（`vue-router` active 类）
- **AND** 无需展开父菜单（因为没有父菜单）

#### Scenario: 路由表新增

- **WHEN** 编辑 `client/src/router/index.js`
- **THEN** 在 `/admin/stock-config` 路由附近追加：
  ```js
  {
    path: '/stkpool',
    component: () => import('@/views/StkPool.vue'),
    meta: { title: '证券池', requiresAuth: true }
  }
  ```
- **AND** MUST NOT 嵌套在 `/admin/stock-config` 的 children 下
- **AND** MUST NOT 在 `app router` 任何 prefix 命名空间下

### Requirement: 数据流 / 清理流程（REQ-STKPOOL-FE-006）

The system SHALL 在删除池/明细时给用户二次确认。

#### Scenario: 删池确认

- **WHEN** user 点击"删除池"按钮
- **THEN** `ElMessageBox.confirm("将清除该池下所有明细，是否继续？", "确认删除")` 弹出
- **AND** 用户确认 → `stkpoolApi.remove(poolId)` → 204
- **AND** 重新拉主表 → 自动选中下一条
- **AND** 用户取消 → 不调 API

#### Scenario: 删明细即时

- **WHEN** user 点击某明细行的"删除"按钮
- **THEN** `ElMessageBox.confirm("确认从池中移除该股票？", "确认")` 弹出
- **AND** 用户确认 → `stkpoolApi.detailRemove(poolId, stockCode)` → 204
- **AND** 刷新当前池明细表

## MODIFIED Requirements

### Requirement: 路由表（追加 /stkpool）

`REQ-FE-001` 路由表 MUST 追加 `/stkpool` 项：

| 路径 | 视图 / 行为 | 鉴权 | 说明 |
|---|---|---|---|
| `/stkpool` | `StkPool.vue` | login | **新增**：证券池管理（左右布局） |

#### Scenario: 路由可达

- **WHEN** user 登录后访问 `/stkpool`
- **THEN** router 解析 `StkPool.vue` 组件
- **AND** Sidebar 自动高亮"证券池"顶级项（与"证券信息"同级别）
- **AND** 鉴权失败（未登录）→ 重定向 `/login`

### Requirement: 侧边栏菜单（v128 追加）

Sidebar `menuItems` 数组 MUST 在"证券信息"顶级项**之后**追加新的顶级项"证券池"，**不嵌套**为子菜单。

```js
// 原结构（保持不动）
{ name: '证券信息', path: '/admin/stock-config' },

// 新结构：在"证券信息"之后追加顶级项
{ name: '证券信息', path: '/admin/stock-config' },
{ name: '证券池', path: '/stkpool' },  // 新增顶级项
```

#### Scenario: 菜单渲染

- **WHEN** Sidebar 渲染
- **THEN** "证券信息" + "证券池" 展示为**平级**顶级项
- **AND** 两者均为 `el-menu-item`（无 `el-sub-menu` 包裹）
- **AND** 视觉上"证券池"紧跟"证券信息"之后
- **AND** 点击任一项 → 路由跳转 + 菜单无展开行为（无父菜单）

### Requirement: API 封装（REQ-STKPOOL-FE-007）

The system SHALL 提供 `client/src/api/stkpool.js` 封装 7 个 API 方法。

```js
export const stkpoolApi = {
  list: () => api.get('/api/stkpool').then(r => r.data.pools),
  create: (data) => api.post('/api/stkpool', data).then(r => r.data),
  update: (id, data) => api.put(`/api/stkpool/${id}`, data).then(r => r.data),
  remove: (id) => api.delete(`/api/stkpool/${id}`),
  detail: (id) => api.get(`/api/stkpool/${id}/detail`).then(r => r.data.details),
  detailAdd: (id, stock_code) => api.post(`/api/stkpool/${id}/detail`, { stock_code }).then(r => r.data),
  detailRemove: (id, stock_code) => api.delete(`/api/stkpool/${id}/detail/${stock_code}`),
}
```

#### Scenario: API 方法导出

- **WHEN** `StkPool.vue` import `stkpoolApi`
- **THEN** 7 个方法全部可用
- **AND** 模板框架参考 `client/src/api/stocks.js`（REQ-FE-521 同模式）
