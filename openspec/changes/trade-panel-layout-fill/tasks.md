# tasks.md — trade-panel-layout-fill

> 实施记录：本 change 在创建前已落地，2 个 commit 已 push 到本地。
> tasks.md 全部标记 `- [x]` 用于回顾性归档。

## 1. uiStore + App.vue 接入 OperationLog v-model

- [x] 1.1 [client/src/stores/ui.js](../../../client/src/stores/ui.js) 加 `oplogExpanded` ref + `setOplogExpanded` + `toggleOplog` actions；export surface 暴露给视图
- [x] 1.2 [client/src/App.vue](../../../client/src/App.vue) 把 `<OperationLog>` 改 `v-model:expanded="uiStore.oplogExpanded"` 双向绑定
- [x] 1.3 commit `09c5315` — `feat(ui): uiStore.oplogExpanded 暴露给视图 + App.vue 接入 OperationLog v-model`

## 2. Trade.vue flex 链布局 + 修 OperationLog 遮挡

- [x] 2.1 [client/src/views/Trade.vue](../../../client/src/views/Trade.vue) script 部分：引入 `useUiStore`，加 `oplogH` computed + `tradeViewStyle` computed 把 `--oplog-h` 注入 `:style`
- [x] 2.2 [client/src/views/Trade.vue](../../../client/src/views/Trade.vue) style 部分：`.trade-view { height: 100% }`，`.trade-grid { flex: 1 }`，`.trade-panels-col > * { flex: 1 1 0; overflow: hidden }`
- [x] 2.3 [client/src/views/Trade.vue](../../../client/src/views/Trade.vue) style 部分：`.trade-panels-col` sticky `max-height: calc(100vh - 80px - var(--oplog-h, 44px))`，窄屏单列堆叠回退保留
- [x] 2.4 [client/src/components/trade/TodayOrdersPanel.vue](../../../client/src/components/trade/TodayOrdersPanel.vue) `bodyMaxHeight` 从 `'calc(100vh - 280px)'` 改为 `'100%'`
- [x] 2.5 [client/src/components/trade/TodayTradesPanel.vue](../../../client/src/components/trade/TodayTradesPanel.vue) `bodyMaxHeight` 从 `'calc(100vh - 360px)'` 改为 `'100%'`
- [x] 2.6 commit `2081efe` — `refactor(client): Trade.vue flex 链让 panel 上下填满 + 修 OperationLog 遮挡`

## 3. 验证

- [x] 3.1 `cd client && npm test -- --run` → 103 tests passed（layout 改动不影响单元测试覆盖范围）
- [x] 3.2 `cd client && npx vite build` → 编译成功，无 syntax error；`Trade-Dk6m42fb.js` chunk 18.27 kB 合理
- [x] 3.3 手动视觉验证（dev 环境）：登录 → /trade → OperationLog 折叠态右侧 panel 填满右列到 oplog 顶部 → 展开 oplog panel 自动收紧 → 缩窄浏览器到 <1100px 单列堆叠

## 提交粒度（按 `feedback_commit_granularity` 拆 2 commit）

| Commit | 文件 | 性质 |
|---|---|---|
| `09c5315` | ui.js + App.vue | 基础: 把 oplogExpanded 提升到 uiStore |
| `2081efe` | Trade.vue + 2 个 panel | 主改动: flex 链 + --oplog-h + bodyMaxHeight 100% |
