# frontend — change delta for `trade-panel-layout-fill`

> 修改 `openspec/specs/frontend/spec.md` 的两个新 ADDED Requirements。
> 不修改既有 REQ，仅追加（按 OpenSpec spec-driven schema `## ADDED Requirements` 规则）。

## ADDED Requirements

### Requirement: OperationLog 折叠状态对视图可见（oPlogExpanded 共享）

The system SHALL 通过 `uiStore` 暴露底部固定 OperationLog 栏的折叠状态，供任意视图响应式读取，
使得依赖 viewport-calc 的布局（典型场景为 sticky 元素的 max-height）能跟随 OperationLog
实际高度变化，避免内容被底部操作记录栏遮挡。

`uiStore` MUST 暴露以下 surface：
- `oplogExpanded: boolean` —— `true` 表示展开（OperationLog 高度 320px），`false` 表示折叠（44px）
- `setOplogExpanded(value: boolean): void` —— 直接设置状态
- `toggleOplog(): void` —— 切换状态

App.vue 的 `<OperationLog>` MUST 用 `v-model:expanded="uiStore.oplogExpanded"` 双向绑定，
保证 OperationLog 内部 toggle 与 uiStore 状态同步；任一端的状态变化 SHALL 通过响应式传播到
所有读取 `uiStore.oplogExpanded` 的视图。

#### Scenario: 默认状态可见

- **WHEN** user 登录后尚未交互
- **THEN** `uiStore.oplogExpanded === false`（默认折叠）
- **AND** OperationLog 高度 = 44px

#### Scenario: 用户展开 OperationLog 后 uiStore 同步

- **WHEN** user 点 OperationLog 标题栏 / 收缩按钮
- **THEN** `uiStore.oplogExpanded` 切换为 `true`
- **AND** OperationLog 高度 = 320px
- **AND** 任一视图（如 Trade.vue）通过 `computed` 读取 `uiStore.oplogExpanded` 的 CSS var MUST
  在同一帧重新求值（Vue reactivity）

#### Scenario: 外部调用 setOplogExpanded 也同步到组件

- **WHEN** 任意代码（含 devtools / 自动化测试）调 `uiStore.setOplogExpanded(true)`
- **THEN** OperationLog 的 `update:expanded` emit 触发 → props 同步 → 折叠状态切到展开

### Requirement: Trade.vue panel 上下填满 + 不被 OperationLog 遮挡

The system SHALL ensure `Trade.vue` 右侧 `.trade-panels-col`（含 TodayOrdersPanel +
TodayTradesPanel 两个 mini-panel）通过 flex 链填满 `.app-content` 的可用垂直空间，
避免在 panel 内容较短时下方出现空白。同时 sticky 行为下的 panel 顶部 SHALL 永远在
OperationLog 上沿之上，不被底部操作记录栏遮挡。

实现 MUST 满足以下行为契约：

- `.trade-view` MUST 设 `height: 100%`（填父容器 `.app-content` 的 content area）
- `.trade-grid` MUST 设 `flex: 1; min-height: 0`（占据 `.trade-view` 中除 `.trade-quicklinks` 外的剩余垂直空间）
- `.trade-panels-col > *` 每个 panel MUST 设 `flex: 1 1 0; min-height: 0; overflow: hidden`
  （强制等分右列高度；任一 panel 都不会因内容短而塌陷留白）
- `.trade-panels-col` MUST 注入 `--oplog-h` CSS var（值取自 `uiStore.oplogExpanded`：
  折叠 44px / 展开 320px）
- 右侧 panel 列的 `max-height` MUST 计算为 `calc(100vh - <AppHeader+padding-y>px - var(--oplog-h, 44px))`，
  保证 sticky panel 底部在 OperationLog 上沿之下
- panel 内部 `el-table` 的 max-height MUST 用 `'100%'`（跟随父 `.tp-body { flex: 1 }`），
  禁止用 `calc(100vh - N)`（避免与外层 sticky max-height 双重截断产生空白）

窄屏（`<1100px` viewport 宽度）下 MUST 切换为单列堆叠：`.trade-grid` 改单列，
`.trade-panels-col` 取消 sticky 与 max-height，让 panel 跟随内容自然高度，保证移动端可读性。

#### Scenario: 默认状态（OperationLog 折叠、宽屏）

- **WHEN** user 登录后导航到 `/trade` 且 OperationLog 折叠（44px）且 viewport ≥ 1100px
- **THEN** `.trade-panels-col` max-height = `calc(100vh - 80px - 44px) = 100vh - 124px`
- **AND** panel 列底部与 OperationLog 顶部对齐（无重叠）
- **AND** 两个 panel 等分右列高度（各 `flex: 1 1 0`）
- **AND** panel 内容（el-table）`max-height: 100%` 填满 panel 内部 `.tp-body`

#### Scenario: OperationLog 展开时 panel 自动收紧

- **WHEN** user 点 OperationLog 标题栏展开（高度变 320px）
- **THEN** `uiStore.oplogExpanded === true`
- **AND** `.trade-view { --oplog-h: 320px }` 通过 `:style` 重新求值
- **AND** `.trade-panels-col` max-height 自动收紧到 `calc(100vh - 80 - 320) = 100vh - 400px`
- **AND** panel 列底部重新对齐到 OperationLog 顶部

#### Scenario: 窄屏 (<1100px) 单列堆叠

- **WHEN** viewport 宽度 < 1100px
- **THEN** `@media (max-width: 1100px)` 生效
- **AND** `.trade-grid { grid-template-columns: 1fr }`（单列）
- **AND** `.trade-panels-col` 取消 `position: sticky` 和 `max-height`
- **AND** panel 跟随内容自然高度（不强制 `flex: 1`）

#### Scenario: 内容短时 panel 仍填满右列（不留底部空白）

- **WHEN** user 当前交易日有 0 笔委托 + 0 笔成交
- **THEN** 两个 panel shell 显示 el-empty（空状态）
- **AND** panel `.tp-shell` 高度仍 = 右列高度的 ½（由 `flex: 1 1 0` 决定）
- **AND** el-empty 居中显示在 panel `.tp-body` 中
- **AND** panel 总高度 = `.trade-panels-col` 高度 - `var(--space-3)` gap
