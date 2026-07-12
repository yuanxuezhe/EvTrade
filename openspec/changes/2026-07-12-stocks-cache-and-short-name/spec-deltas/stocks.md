# Spec Delta: stocks capability — 真分页 + 前端缓存 + autocomplete

**Change**: 2026-07-12-stocks-cache-and-short-name
**Target**: `openspec/specs/stocks/spec.md`

## 增量内容

### 新增 REQ-STOCK-006: 真分页查询 + 服务端筛选

**Given** stocks 表存量 5529 行(将来 ETF 加进来破 6000)
**When** 前端调用 `GET /api/stocks`
**Then** 必须满足:

- 查询参数:
  - `page`: int, 默认 1, ≥ 1
  - `page_size`: int, 默认 100, 范围 1..500
  - `limit`: int, **兼容老客户端**(deprecated, page_size 优先),无上限但无 page 返回
  - `sector`: str, 可选,精确匹配板块
  - `keyword`: str, 可选,模糊匹配 stock_code 前缀或 stock_name 含
  - `is_t0_able`: bool, 可选,回转标志过滤
- 响应:
  ```json
  {
    "code": 0,
    "msg": "ok",
    "list": [...],
    "total": 5529,
    "page": 1,
    "page_size": 100
  }
  ```
- 排序: `ORDER BY stock_code ASC`
- `total` = COUNT(*),与 `len(list)` 无关
- 鉴权: 任意登录用户(同 v23)

**Rationale**: v23 客户端硬塞 `limit: 1000`,超过 1000 的数据看不到。v25 改用真分页,
前端 AdminStockConfig.vue 表格直接渲染后端分页结果,翻页即请求。

### 新增 REQ-STOCK-007: 前端全量缓存 (Stock cache layer)

**Given** AdminStockConfig 页面需要支持 stock_code autocomplete 输入
**When** 用户打开 AdminStockConfig.vue
**Then** 必须满足:

- Pinia store `useStocksStore` 持有 2 个数据源:
  - `cache: Stock[]`: 全量 5529,内存缓存(刷新页面重拉)
  - `pageRows: Stock[]`: 当前页,直接绑 el-table
- 加载流程:
  1. onMounted → `loadCache()`: 循环 `?page=N&page_size=100` 直到 `total === cache.length`
  2. 同时 `fetchPage(1, 100)` 渲表格第一页
  3. 用户翻页 → `fetchPage(page, pageSize)`,不发 loadCache
- PATCH 同步流程 (`updateStock(code, payload)`):
  1. 后端 PATCH 成功返更新后的 stock
  2. 同步更新 `cache` 中对应行(按 stock_code 查找)
  3. 同步更新 `pageRows` 中对应行(如果在当前页)
  4. 不重拉 cache
- 加载态: `cacheLoading: boolean`(用于 progress 显示)
- 错误处理: cache 拉取失败 → store.error,不影响 pageRows 显示

**Rationale**: autocomplete 需要全量数据做客户端筛选;但表格分页走后端,
避免一次返 5529 条卡死 el-table。两者解耦,各自独立刷新。

### 新增 REQ-STOCK-008: StockCodeAutocomplete 组件

**Given** 用户需要在 AdminStockConfig 编辑弹窗输入 stock_code
**When** 渲染 `<StockCodeAutocomplete v-model="editingCode" />`
**Then** 必须满足:

- Props:
  - `modelValue: string`: 双向绑定 stock_code
  - `placeholder: string`: 占位符
  - `disabled: boolean`: 是否禁用
  - `pageSize: number`: 候选展示上限,默认 50
- Emits:
  - `update:modelValue`: 输入变化时触发
  - `select(stock)`: 用户点击候选触发,**仅当选中真实存在的 stock 才触发**
- 数据源: 复用 `useStocksStore.cache`(全量)
- 筛选逻辑(任一命中即展示):
  - `stock_code` 前缀匹配(大小写不敏感)
  - `stock_name` 包含匹配(大小写不敏感)
  - `short_name` 前缀匹配(大小写不敏感)
- 排序: 优先 `stock_code` 前缀命中 → 再 `short_name` 前缀命中 → 再 `stock_name` 包含
- 无效输入:
  - 候选列表为空 → 不 emit `select`,仅 emit `update:modelValue`
  - 用户按 Enter 但无候选 → 不做任何事
- 显示格式:
  - 主文本: `stock_code`(等宽字体)
  - 副文本: `stock_name` + `[short_name]`

**Rationale**: 防止用户输入不存在的 stock_code 进入编辑流程;
拼音首字母输入「PAYH」能快速定位「平安银行」,符合用户硬性偏好"必须输入存在的证券代码"。

## REQ-STOCK-003 增量: admin 白名单 +1 字段

v25 加 `short_name` 到白名单:

**白名单字段(v25 6 字段)**:
- `stock_name` / `sector` / `is_t0_able` / `min_buy_qty` / `trade_unit` / `short_name`

**Scenario: admin 编辑 short_name 字段**

- **GIVEN** admin 调用 `PATCH /api/stocks/{code}` with body `{short_name: "PAYH"}`
- **WHEN** 请求处理
- **THEN** short_name 被更新到 DB
- **AND** 返回的 stock 对象含 `short_name: "PAYH"`