# Tasks: 2026-07-12-universalize-stockcode-autocomplete

## 1. OpenSpec 4 件套（Commit 1）
- [x] proposal.md
- [x] tasks.md
- [x] spec-deltas/stocks.md（REQ-STOCK-007 全局化 autocomplete）
- [x] spec-deltas/client-architecture.md（client 架构：全局 cache 预加载）

## 2. StockCodeAutocomplete 增强（Commit 2）
- [x] 已实现（v25）: stock_code/name/short_name 三路筛选 + 排序
- [x] 新增 `selected` 事件暴露完整 stock 对象
- [x] 新增 `size` prop 透传
- [x] 错误降级：cache 加载失败时 input 仍可手动输入（不 throw）

## 3. 替换 3 个下单入口（Commit 3）
- [x] OrderForm.vue 替换 el-input 为 StockCodeAutocomplete
- [x] T0TaskCreateDialog.vue 替换 el-select 为 StockCodeAutocomplete
- [x] StrategyConfig.vue 替换 el-input 为 StockCodeAutocomplete
- [x] 验证父组件 @update:stock-code / 行情拉取逻辑

## 4. 全局预加载 cache（Commit 4）
- [x] App.vue onMounted 触发 useStocksStore.loadCache()
- [x] 验证 Trade.vue 进入 0 等待（cache 已 loaded）
- [x] 缓存进度不阻塞首屏渲染

## 5. 验证 + push（Commit 5，可选）
- [x] npm run build 通过
- [x] 浏览器实测 3 个下单入口 autocomplete
- [x] git push origin master