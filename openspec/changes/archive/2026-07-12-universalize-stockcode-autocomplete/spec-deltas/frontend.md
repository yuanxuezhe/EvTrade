# Spec Delta: frontend — stocks store + cache 全局预加载

**Change**: 2026-07-12-universalize-stockcode-autocomplete
**Target**: `openspec/specs/frontend/spec.md`

## 增量内容

### REQ-FE-003 (修订): Pinia stores 新增 `stocks`

`client/src/stores/stocks.js` MUST 注册到 Pinia，列表扩展为：

| Store | 职责 | 数据源 |
|---|---|---|
| ... | ... | ... |
| `stocks` | **股票代码 autocomplete 全量缓存** (v25/v26) | `/api/stocks?page=N&page_size=100` 循环拉 + 内存 |

`stocks` store 关键 surface：
- `cache: ref([])` — 全量 5529 内存缓存
- `cacheLoaded: ref(false)` — 加载完成标记（autocomplete 0 等待判断）
- `cacheLoading: ref(false)` — 加载中（防重入）
- `cacheProgress: ref(0)` — 0..1 加载进度
- `pageRows: ref([])` / `total: ref(0)` / `page: ref(1)` / `pageSize: ref(20)` — 表格分页
- `loadCache({ page_size=100 })` — 循环 page=1..N 拉全量
- `searchCache(query, limit=50)` — 三路 OR 筛选（code/name/short_name）
- `fetchPage(extraParams)` — 后端单页拉
- `openEdit/closeEdit/saveEdit` — Admin 编辑

### 新增 REQ-FE-010: stocks cache 全局预加载（v26）

**Given** `StockCodeAutocomplete` 依赖 `useStocksStore().cache`，首次进入 Trade/T0/Strategy
下单页面需等待 18s（分页循环拉 5529 行）

**When** App 启动

**Then** MUST 满足：

- `App.vue` `onMounted` 立即触发 `useStocksStore().loadCache()`
- **不阻塞首屏渲染**（异步执行，与路由跳转并行）
- 用户进入 `/trade` / `/t0-trade` / `/strategy-trade` 时 cache 预加载已就绪，
  `cacheLoaded=true`，`StockCodeAutocomplete` `fetch-suggestions` 立即可用
- 浏览器刷新 → cache 清空 → 重新后台加载
- **cache 已被一个页面加载**，其他页面切换 0 重新拉取（内存复用）
- 加载失败 → `store.cacheError` 非空，下次进 Trade 时 `StockCodeAutocomplete.ensureCache()`
  可重试

#### Scenario: 首次访问 EvTrade

- **GIVEN** 用户浏览器打开 http://host/
- **WHEN** App.vue mounted
- **THEN** 后台异步 `useStocksStore.loadCache()`（不阻塞首屏）
- **WHEN** 用户导航到 `/trade`
- **THEN** cache 已 loaded，autocomplete 立即可用

#### Scenario: 已登录用户刷新页面

- **GIVEN** cache 已 loaded
- **WHEN** F5 刷新页面
- **THEN** cache 清空
- **AND** App.vue 重新 `loadCache()`，进 Trade 页面时大概率已就绪

### 新增 REQ-FE-011: StockCodeAutocomplete 通用组件契约（v26）

**Given** 下单入口（交易下单/快速做T/策略交易）需要股票代码输入体验

**When** 设计通用 autocomplete 组件

**Then** MUST 满足：

- 组件位置：`client/src/components/StockCodeAutocomplete.vue`
- Props:
  - `modelValue: string` — v-model stock_code
  - `placeholder: string` — 默认"输入代码 / 名称 / 首字母"
  - `disabled: boolean` — 默认 false
  - `clearable: boolean` — 默认 true
  - `triggerOnFocus: boolean` — 默认 false
  - `size: 'default' | 'small' | 'large'` — 透传 el-autocomplete size
- Emits:
  - `update:modelValue (string)` — 输入变化（候选未选中时也会发）
  - `select (stock)` — 候选被选中时发完整 stock 对象
  - `blur ()` — 失焦
- 三路 OR 筛选（按 score 排序）：code 前缀(3) > short_name 前缀(2) > name 包含(1)
- 候选上限 50 条
- **必须命中 cache 中真实存在的 stock_code** 才允许确认
- 错误降级：`loadCache()` 失败时 input 仍可手动输入，候选列表空

#### Scenario: 交易下单输入"600519"

- **GIVEN** cache 已 loaded
- **WHEN** OrderForm 内 StockCodeAutocomplete 输入 `600519`
- **THEN** 候选"600519.SH 贵州茅台 [GZMT]" 弹出（score=3）
- **AND** 点击候选 → v-model 填入 `600519.SH` + emit `update:modelValue` + emit `select(stock)`
- **AND** OrderForm 收到 emit → 触发父组件 Trade.vue 拉行情