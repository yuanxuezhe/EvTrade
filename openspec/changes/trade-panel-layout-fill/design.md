## Context

Trade.vue 在 2026-07-04 早些时候通过 commit `045f7f9` 把 v12 拆出的 `TodayOrders.vue` /
`TodayTrades.vue` 完整版路由抽成了两个 mini-panel（`components/trade/TodayOrdersPanel.vue`
+ `TodayTradesPanel.vue`），嵌入到 `/trade` 右侧，详见
`openspec/changes/archive/2026-07-04-embed-trade-panels/`（如未归档则在 changes/）。

实施后用户反馈两个布局缺陷：

1. **"窗口下面空白太多，上下填满"**：viewport 大、panel 内容短时，panel 只占自身自然高度，
   下方留空
2. **OperationLog 遮挡**：`.trade-panels-col` 用 `max-height: calc(100vh - 100px)` 没减底部
   固定 OperationLog（折叠 44px / 展开 320px），导致 sticky 状态下 panel 底部被覆盖

约束：
- 仅前端改动，不动后端 / API / RPC / ws 协议
- 已有 103 个单元测试需保持全过
- 不能引入新的依赖（项目用 Vue 3 + Element Plus + Pinia，已是现代浏览器栈）

## Goals / Non-Goals

**Goals:**
- Trade.vue 右侧 panel 列在 viewport 内上下填满，无空隙
- Sticky panel 自动跟随 OperationLog 折叠 / 展开状态
- 单元测试零回归
- 不引入新依赖、不破坏窄屏单列堆叠的回退行为

**Non-Goals:**
- 不重构 panel 内部逻辑（已上 commit 的滚动进度条 / 撤单交互保持不变）
- 不动 `/today/orders` / `/today/trades` 独立路由（仍是完整版 view）
- 不改 OperationLog 自身的折叠机制（仅暴露状态）
- 不做 e2e 测试（项目无 Playwright 配置）

## Decisions

### D1: uiStore 暴露 oplogExpanded（vs 局部 prop + emit 链）

**决定**：把 OperationLog 折叠状态提升到 `uiStore.oplogExpanded`，App.vue 通过
`v-model:expanded="uiStore.oplogExpanded"` 双向绑定。

**为什么不用 provide/inject 或 prop 链**：
- Trade.vue 与 OperationLog 是兄弟组件（都在 App.vue 顶层），中间隔着 `<router-view>`，
  provide/inject 跨 router-view 边界传递需要额外 setup
- prop 链需要把 oplog state 从 OperationLog 提到 App.vue → 再下沉到 Trade.vue →
  反复 emit，每加一个需要知道的视图都得改 App.vue
- uiStore 是项目既定模式（已经在持有 sidebarCollapsed / mobileSidebarOpen / theme），
  扩展一个字段零成本

**为什么不用 localStorage 持久化**：
- 用户期望 OperationLog 折叠态是会话级（刷新页面后回到默认折叠），与现有 uiStore
  内存态语义一致（sidebarCollapsed 反而因为"个人偏好"持久化）
- 与 OperationLog 现有的 `collapsed = ref(true)` 默认折叠行为对齐

### D2: `--oplog-h` CSS var 注入（vs JS 监听 + inline style 覆盖）

**决定**：Trade.vue 通过 `:style="{ '--oplog-h': oplogH.value }"` 把 uiStore.oplogExpanded
转成 CSS 自定义属性，在 `max-height` calc 里引用。

**为什么不用 ResizeObserver 监听 OperationLog 的 DOM size**：
- OperationLog 是 `position: fixed` 元素，DOM offsetHeight 是视口坐标，但 sticky panel 的
  max-height 已经在 viewport 坐标系算出来（用 `100vh`），直接读 OperationLog 的 height
  反而要二次坐标转换（更绕）
- ResizeObserver 在 OperationLog 折叠/展开动画中（`transition: box-shadow` /
  slideDown）会触发多次回调，需要防抖
- CSS var 路径天然支持任意粒度的子元素读取，扩展容易

**为什么用 `100vh` 而非父容器 `100%`**：
- Trade.vue 嵌入位置是 `.app-content` (`overflow: auto; padding-bottom: 60px`)。
  在该 content area 里 panel 想要"sticky 跟随滚动且 max-height 与 viewport 对齐"必须用
  viewport 单位，否则 sticky 期间高度参照系不稳
- 80px 减项：AppHeader (~56px) + `.app-content { padding: var(--space-6) }` 上 24px = 80px

### D3: bodyMaxHeight 改 `'100%'`（vs 动态 ResizeObserver JS 同步）

**决定**：panel 内部 `el-table :max-height` 从 `'calc(100vh - 280px)'` /
`'calc(100vh - 360px)'` 改为 `'100%'`。

**为什么不是 ResizeObserver 监听 `.tp-body` 实时更新**：
- el-table 的 `max-height` 一旦在 mounted 后改值，Element Plus 内部会重建 virtual scroll
  wrapper，造成滚动位置跳到 0 / 闪烁
- 用 `'100%'` 后 el-table 始终 = 父 `.tp-body { flex: 1 }` 的高度，跟着父容器 resize
  自然响应
- 唯一需要"双重 max-height"的原因是 panel 父层已有 sticky max-height 限高，
  panel 内部再来 `100vh - N` 会比 panel 自身可用高度更小，引入空白

### D4: flex 链 + grid 列（vs 单一 flex column / 单一 grid 全行）

**决定**：`.trade-view { height: 100%; flex column }` + `.trade-grid { flex: 1; display: grid;
grid-template-columns: 480px 1fr }` + `.trade-panels-col > * { flex: 1 1 0 }`。

**为什么不是单一 flex column 整行**：
- 左列（OrderForm + QuotePanel）和右列（两个 panel）需要等高（在桌面端不能一个高一
  个矮），grid 的 `align-items: stretch` 默认值天然解决
- 左列内容高度不固定（OrderForm 始终 ~360px，QuotePanel 根据是否展开动态 ~150-450px），
  用 flex baseline 对齐反而不齐

**为什么 `.trade-panels-col > * { flex: 1 1 0 }` 而不是 `:nth-child` 分别设高度**：
- 未来若加第三个 mini-panel（如今日持仓缩略），无需改 CSS，flex 1 1 0 自动等分
- 与左列内容的"自然高度"对偶：左列内容短不空、右列 panel 短也不空

### D5: 保留 sticky（vs 移除 sticky 改外层滚动）

**决定**：保留 `position: sticky; top: 80px` + max-height cap。

**为什么保留**：
- 当左列 OrderForm / QuotePanel 总高度 > viewport 时（典型：480 + 450 = 930 ≈ 90vh），
  页面需要滚动。sticky 让右 panel 在用户滚动过程中始终贴顶可见，符合"同屏看委托"的
  设计意图（参考 commit `045f7f9` 的设计动机）
- 当左列高度 < viewport 时，sticky 不触发、不影响布局

**为什么 top: 80px**：`.app-content { padding-top: var(--space-6) }` = 24px，AppHeader
约 56px。合计 80px，确保 sticky 后 panel 顶部仍在 AppHeader + 内容 padding 之下。

## Risks / Trade-offs

**R1: uiStore.oplogExpanded 与 OperationLog 内部 collapsed ref 双源** →
OperationLog 内部仍持有 `collapsed = ref(true)`，通过 `watch(props.expanded)` 同步。
两个 ref 之间靠 `v-model:expanded` + `update:expanded` 双向绑定协调，无冲突。
（备选：可直接读 uiStore 替代内部 ref，但会侵入 OperationLog 抽象层；当前实现遵循既有
`v-model:expanded` 模式）

**R2: `--oplog-h` CSS var 兼容性** →
所有现代浏览器（Chrome 49+ / Firefox 31+ / Safari 9.1+）支持。项目用 Vite 5，默认目标
浏览器集已 ≥ 2022，无风险。

**R3: panel 内部 el-table `max-height: 100%` 在 panel 未限高时表现** →
若 panel 父层意外没传 height（如未捕获的回归），el-table 会撑到 100% × 0 = 0。已通过
外层 `.trade-panels-col > * { flex: 1 1 0; overflow: hidden }` 强约束，min-height: 0 也
保证能缩。窄屏 `@media (max-width: 1100px)` 重置为 `flex: 0 0 auto; overflow: visible`。

**R4: 单元测试不覆盖布局** →
现有 vitest 都是逻辑/工具测试，layout 没有 e2e 测试。验证依赖手动 / 视觉。如果未来引入
Playwright，可以加 visual regression 测试。

## Migration Plan

无 schema 迁移、无数据迁移，纯粹前端代码改动。

部署：
1. merge 此 change 的 commits
2. 前端 build → vite build → dist 直接替换
3. 无 server 重启需求

回滚：
- revert 即可，无服务端状态依赖
- 若仅回滚 commit 2（refactor），OperationLog 状态已暴露在 uiStore 但未使用，无副作用

## Open Questions

无。
