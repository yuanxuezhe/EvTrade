## Why

Trade.vue 右侧嵌入的「今日委托」+「今日成交」mini-panel 当前实现 (commit `045f7f9` 之后) 存在两个布局缺陷：

1. **下方空白过多**：viewport 视口大但 panel 短时，面板只占自身自然高度（header + 行数），下方留出大片空白，没填满可用空间。
2. **OperationLog 遮挡**：`.trade-panels-col { max-height: calc(100vh - 100px) }` 没有减掉底部固定 OperationLog 高度（折叠 44 / 展开 320），导致 sticky panel 底部被操作记录栏覆盖。

修复需要：

- 把 OperationLog 折叠状态提升到 `uiStore`，让任何视图都能跟随
- Trade.vue 改 flex 链 + grid 列布局，让 panel 等分可用区
- panel 内部 el-table 的 max-height 从 `100vh - NN` 改为 `100%`（跟随父容器），消除双重 max-height

## What Changes

- **`client/src/stores/ui.js`** — 新增 `oplogExpanded` ref + `setOplogExpanded` + `toggleOplog` actions
- **`client/src/App.vue`** — OperationLog 改 `v-model:expanded="uiStore.oplogExpanded"`，让折叠状态对外可见
- **`client/src/views/Trade.vue`** — 改用 flex 链布局（`.trade-view { height: 100% }` → `.trade-grid { flex: 1 }` → `.trade-panels-col > * { flex: 1 1 0 }`）；注入 `--oplog-h` CSS var 让 sticky `max-height: calc(100vh - 80px - var(--oplog-h, 44px))` 跟随 OperationLog 高度
- **`client/src/components/trade/TodayOrdersPanel.vue`** + **`TodayTradesPanel.vue`** — `bodyMaxHeight` 从 `calc(100vh - 280/360px)` 改为 `'100%'`，跟随父 `.tp-body` (`flex: 1`)

无 BREAKING 变更。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- **`frontend`** — 增加 2 个 REQ：
  - REQ-FE-013（oPlogExpanded 共享）：`uiStore` MUST 暴露 `oplogExpanded` 状态供视图响应式读取
  - REQ-FE-014（panel 上下填满）：`Trade.vue` 右侧 panel 列 SHALL 用 flex 链填满 `.app-content` 可用区（不留底部空白）；sticky panel max-height MUST 减掉 OperationLog 高度（由 `--oplog-h` CSS var 驱动）

## Impact

- 纯前端代码改动（5 个文件）
- 不影响 API 契约、不影响后端、不影响 RPC/ws 协议
- 单元测试不受影响（103 测试不变，全过）
- 视觉验证：需要手动打开 `/trade` 检查三种状态——
  1. 默认 OperationLog 折叠，panel 填满到 oplog 上沿
  2. 展开 OperationLog，panel max-height 自动收紧（约 270px）
  3. 窄屏 (<1100px) 仍走单列堆叠 + 自然高度
