# Spec Delta: stocks capability — StockCodeAutocomplete 通用化

**Change**: 2026-07-12-universalize-stockcode-autocomplete
**Target**: `openspec/specs/stocks/spec.md`

## 增量内容

### 新增 REQ-STOCK-007: 通用 StockCodeAutocomplete 组件（下单入口统一）

**Given** 前端有多个"股票代码输入"入口（交易下单 / 快速做T / 策略交易）

**When** 设计股票代码 autocomplete 组件

**Then** 必须满足：

- 组件位置：`client/src/components/StockCodeAutocomplete.vue`
- 数据源：`useStocksStore` 的 `cache` 字段（v25 全量 5529 内存缓存）
- 三路 OR 筛选（按 score 排序）：
  - `stock_code` 前缀匹配 → score=3（最高优先）
  - `short_name` 前缀匹配 → score=2（次之，v25 拼音首字母）
  - `stock_name` 包含匹配 → score=1（兜底）
- 候选数量上限：50 条
- 候选展示：`stock_code` + `stock_name` + `[short_name]` 三列
- **必须命中 cache 中真实存在的 stock_code** 才允许确认（v25 用户硬性偏好）
- 输入空 / 仅空白字符 → 不展示候选
- **v26 新增 API**：
  - `@select(stock)` 事件：候选被选中时触发，参数为完整 stock 对象
  - `size` prop：透传 el-autocomplete size（'default' | 'small' | 'large'）
  - `placeholder` prop：默认"输入代码 / 名称 / 首字母"
  - `clearable` prop：默认 true
  - `triggerOnFocus` prop：默认 false（focus 不展示所有候选，避免误触）
- 错误降级：`loadCache()` 失败 → input 仍可手动输入，候选列表为空

#### Scenario: 交易下单页面输入"600519" 弹出贵州茅台

- **GIVEN** admin/trader 已登录 + cache 已加载（5529 条）
- **WHEN** 进入 `/trade` 页面，在股票代码输入框输入 `600519`
- **THEN** autocomplete 弹出候选"600519.SH 贵州茅台 [GZMT]"（score=3）
- **AND** 点击候选 → input 框填入 `600519.SH` → 触发 OrderForm 的 emit `update:stock-code`
- **AND** Trade.vue 收到 `update:stock-code` → 触发行情拉取

#### Scenario: 拼音首字母筛选

- **GIVEN** cache 已加载
- **WHEN** 输入 `PAYH`
- **THEN** 候选"000001.SZ 平安银行 [PAYH]"（score=2）

#### Scenario: cache 未加载完时首次输入

- **GIVEN** 用户首次访问 StockCodeAutocomplete，cache 还在后台加载
- **WHEN** 立即输入 `600519`
- **THEN** autocomplete 自动等待 `ensureCache()` 完成（最长 ~18s）
- **AND** 加载完成后弹出候选
- **AND** **不会**因加载失败抛出异常阻断用户输入

### 新增 REQ-STOCK-008: 全局 cache 预加载

**Given** StockCodeAutocomplete 依赖 `useStocksStore.cache`，首次进入 Trade 页面需等 18s

**When** 用户首次访问 EvTrade

**Then** 必须满足：

- App.vue 启动时立即后台触发 `useStocksStore.loadCache()`
- 不阻塞首屏渲染（异步执行）
- 已登录用户进入 `/trade` / `/t0-trade` / `/strategy-trade` 时 cache 已 `cacheLoaded=true`，0 等待
- cache 已加载的页面之间切换 0 重新拉取（内存复用）
- 浏览器刷新页面 → cache 清空 → 重新后台加载
- 加载失败 → store.cacheError 非空，下次进 Trade 时 fetch-suggestions 重试

#### Scenario: 首次访问 EvTrade

- **GIVEN** 用户浏览器打开 http://host/
- **WHEN** App.vue mounted
- **THEN** 后台异步 `useStocksStore.loadCache()`（不阻塞首屏）
- **WHEN** 用户导航到 `/trade`
- **THEN** cache 已 loaded，autocomplete 立即可用