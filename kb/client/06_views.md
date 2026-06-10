# Client · 06 · 页面级视图（Views）

> 9 个页面，按 `client/src/views/` 顺序。

## 1. `Login.vue` — 登录

### 1.1 路由
`/login`，layout=blank，public

### 1.2 布局
左品牌区（logo + slogan + hero + feature list） + 右登录卡（form + 主题切换）

### 1.3 数据
```js
form = reactive({ username: '', password: '' })
remember = ref(true)  // 默认勾选
formRef, loading
```

### 1.4 校验规则
- username 必填
- password 必填 + ≥ 6 位

### 1.5 行为
1. `onMounted` 从 `localStorage.evtrade-remember-username` 恢复用户名
2. 提交 → `authStore.login(u, p)` → 成功保存 username → `ElMessage.success` → 跳 `redirect || '/'`
3. 失败 → `ElMessage.error(detail)`

### 1.6 错误处理
- 401 → `'用户名或密码错误'`
- 403 → `'账号已禁用'`

## 2. `Dashboard.vue` — 仪表盘

### 2.1 路由
`/`

### 2.2 数据流
`onMounted` 并行拉取 asset / orders / trades / positions

### 2.3 三大区块
1. **KPI 卡**（4 个 StatCard）
   - 总资产 / 可用资金 / 持仓市值 / 今日盈亏
   - 今日盈亏 = 成交 SELL 金额 - 成交 BUY 金额
   - 今日盈亏 % = pnl / total_asset * 100
2. **资产分布 + 委托概况**
   - 资产饼图（EChart doughnut）
   - 委托状态聚合（5 大类：done/working/pending/terminal/rejected）
3. **持仓 Top5 + 最近委托 6 条**

## 3. `Position.vue` — 持仓管理

### 3.1 路由
`/positions`

### 3.2 数据流
`onMounted` → `positionStore.fetchPositions`

### 3.3 顶部 4 个 stat-pill
持仓数 / 总持仓量 / 可用量 / 今日净变动

### 3.4 工具栏
- 搜索（按代码/名称模糊）
- 刷新
- 日初初始化下拉（全部 / 仅选中）

### 3.5 表格
`PositionTable.vue` 组件，点击行打开抽屉

### 3.6 抽屉
- 标题：`{stockCode} - 持仓明细`
- 内容：`PositionDetail.vue`
- Props: `:position, :orders, :trades`

### 3.7 日初初始化
```js
ElMessageBox.confirm(...) // 二次确认
for (const pos of positions) {
  await positionStore.initPosition(pos.stock_code)
}
```

## 4. `Trade.vue` — 交易下单

### 4.1 路由
`/trade`，requiresTrader

### 4.2 布局
- 左 360px：OrderForm + 快捷股票（6 个常用股）
- 右 1fr：今日委托表

### 4.3 委托表功能
- 筛选：全部 / 未完成 / 已成交
- 字段：时间 / 股票 / 方向 / 数量 / 价格 / 已成 / 状态 / 操作
- 操作：可撤单状态（`unreported / pending_report / reported / reported_cancel / partial / partial_pending_cancel / pending`）显示"撤单"按钮
- **5s 自动刷新**（setInterval + onUnmounted clear）

### 4.4 撤单
`ElMessageBox.confirm` → `orderStore.cancelOrder(orderId)`

## 5. `Asset.vue` — 账户资金

### 5.1 路由
`/asset`

### 5.2 数据
仅 `useAssetStore.fetchAsset()` + `useUiStore.theme`（用于切换 ECharts 主题）

### 5.3 区块
1. Hero 区：总资产大字 + 现金/市值/冻结占比 + 饼图
2. 4 张资金详情卡：可用 / 冻结 / 持仓市值 / 总资产（含进度条）
3. 资金说明：4 项 Dot + 文案

## 6. `Orders.vue` — 委托查询

### 6.1 路由
`/orders`

### 6.2 统计卡（5 个）
委托总数 / 已成交 / 部成 / 待成交 / 已撤

### 6.3 筛选
- 关键词（代码模糊）
- 方向（BUY/SELL）
- 状态（STATUS_OPTIONS）
- 清空 / 刷新 / 导出 CSV

### 6.4 表格字段
时间 / 代码 / 方向 / 委托量 / 委托价 / 成交量 / 成交价 / 成交率（进度条）/ 状态 / 类型 / 委托编号

### 6.5 导出 CSV
列：时间, 股票代码, 方向, 委托量, 委托价, 成交量, 成交价, 状态, 类型, 委托编号
文件名前缀：`委托查询_YYYY-MM-DD.csv`（BOM 防 Excel 乱码）

### 6.6 分页
- `v-model:current-page`、`v-model:page-size`
- sizes = [10, 20, 50, 100]

## 7. `Trades.vue` — 成交查询

### 7.1 路由
`/trades`

### 7.2 统计卡（5 个）
成交笔数 / 买入笔数 / 卖出笔数 / 买入金额 / 卖出金额

### 7.3 筛选
关键词（代码模糊）+ 方向

### 7.4 表格字段
成交时间 / 股票代码 / 方向 / 数量 / 价格 / 金额（qty*price） / 成交编号 / 委托编号

### 7.5 导出 CSV
列：成交时间, 股票代码, 方向, 成交数量, 成交价格, 成交金额, 成交编号, 委托编号

## 8. `Users.vue` — 用户管理

### 8.1 路由
`/users`，requiresAdmin

### 8.2 统计卡（5 个）
总用户数 / 管理员 / 交易员 / 只读用户 / 已禁用

### 8.3 筛选
关键词（username/email/full_name 模糊）+ 角色

### 8.4 表格字段
ID / 用户名（带头像 + 姓名） / 邮箱 / 角色（彩色 chip） / 状态（el-tag） / 最近登录 / 创建时间 / 操作

### 8.5 操作
- 编辑：弹编辑对话框
- 重置密码：弹重置密码对话框
- 启用/禁用：toggle，确认后调 `userApi.update({is_active: ...})`
- 删除：确认后调 `userApi.delete(id)`（自己不可删）

### 8.6 两个内联 dialog
- 新建/编辑：username/password/role/email/full_name/is_active
  - username 校验：`^[A-Za-z0-9_\-.]{3,32}$`
  - email 校验：`^[\w.+-]+@[\w-]+\.[\w.-]+$`
- 重置密码：new_password + confirm

## 9. `Profile.vue` — 个人资料

### 9.1 路由
`/profile`

### 9.2 数据
`authStore.user`（onMounted 触发 `fetchMe`）

### 9.3 三大区块
1. Hero 卡：头像 + 姓名 + 角色 badge + 邮箱 + 上次登录 + 注册时间
2. 个人资料表单：username / role 不可改；姓名 / 邮箱可编辑
3. 权限说明（3 卡）：查看 / 交易 / 用户管理，按 `isAuthenticated / isTrader / isAdmin` 灰显或高亮

### 9.4 修改密码按钮
打开 `<ChangePasswordDialog v-model="pwdDialogVisible"/>`

## 10. 视图侧交互小细节

| 视图 | 特性 |
|------|------|
| `Dashboard` | 资产/委托/持仓/最近委托四区 |
| `Position` | 行点击开抽屉；下拉初始化 |
| `Trade` | 5s 自动轮询；快捷股票 |
| `Asset` | hero 区大字 + 饼图 |
| `Orders/Trades` | 关键字搜索 + 状态/方向过滤 + CSV 导出 + 分页 |
| `Users` | 头像按 role 着色；行内操作 4 按钮 |
| `Profile` | 权限可视化卡片 |
| `Login` | 分栏布局（品牌 + 表单） |
