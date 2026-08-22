## Purpose

委托 / 成交 **当日数据**通过 Pinia + 浏览器 IDB write-through 持久化，无需重新拉取即可在 F5 / 重新打开 tab 后立即恢复（< 200ms）。positions / asset 不持久化（实时性 + 安全考虑）。

> **与 `orders-trades-history-query` 的边界**：
> - **本 spec（intraday-orders-trades-cache）**：仅当**当日（`activeDay`）** 数据；通过 Pinia 内存 + IDB 持久化；面板组件（TodayOrdersPanel / TodayTradesPanel）内嵌 Trade.vue
> - **兄弟 spec（orders-trades-history-query）**：按 `start_date` / `end_date` 区间查询；**不走** Pinia / IDB；每次独立 HTTP GET `/api/orders/history` 或 `/api/trades/history`
>
> 两者**不重叠**：当日数据走 intraday panel（实时），跨日查询走 history view（按需拉取）。同一笔委托在 activeDay 走 intraday 路径；切日后（activeDay 变更）通过 bootstrap 重灌，**不再**走 intraday panel。

## Requirements

### Requirement: 今日委托 panel（TodayOrdersPanel 内嵌于 Trade.vue）

The system SHALL 提供 `client/src/components/trade/TodayOrdersPanel.vue` 组件，作为
`Trade.vue` 右侧 sticky 列的上方面板，承载今日委托数据的实时展示：

- **数据源**：`useHoldingsStore().orders`，Pinia 内存 + IDB write-through
- **范围过滤**（panel-local computed `todayOrders`）：
  - `trd_date === activeTrdDate`（仅当日）
  - `Number(order_flag) !== 1`（排除 cancel-row，统计口径干净）
- **分页**：el-pagination 默认 20 行/页 (pageSizes `[10, 20, 50, 100]`)，panel-local state，不入 Pinia
- **撤单按钮**：每行 `canCancel(row) === true` 时显示 `el-button type="danger" link size="small"` "撤"按钮
  - `canCancel(row)` 守卫 = `order_flag !== 1` AND `status` 不在 broker 终态集 `{51, 52, 53, 54, 55, 56, 57}`
  - 点击 → `ElMessageBox.confirm` 弹窗 → `orderStore.cancelOrder(row.order_no, row.trd_date)`
- **panel 视觉**：mini 卡 (`.tp-shell.content-card`)，含 header (`h3` + 笔数 + 刷新按钮) + body el-table

#### Scenario: panel 数据流（v13 嵌入模式）

- **WHEN** user 登录后打开 `/trade`
- **AND** `holdings.bootstrap()` 已完成（Pinia `orders.value` 已填今日数据）
- **THEN** `TodayOrdersPanel.todayOrders` MUST 渲染当日委托的 `order_flag !== 1` 子集
- **AND** MUST NOT 发任何 HTTP 请求（不走 `/api/orders`）
- **AND** ws `order_update` 来时 panel MUST 自动更新（Vue reactivity + `applyOrderPush`）

#### Scenario: panel 分页与 cache 共存

- **WHEN** 当前交易日有 50 笔委托 (≥20)
- **THEN** el-pagination MUST 显示，默认 page=1, pageSize=20 渲染前 20 笔
- **AND** ws 推送新增委托 → `orders.value` 数组增长 → pagination `:total` 同步增加
- **AND** ws 推送修改已渲染行的 `status` → 当前页对应 row MUST 实时更新状态标签

#### Scenario: panel 撤单仅作用于 activeDay 行

- **WHEN** panel 的 `todayOrders` computed 已过滤 `trd_date === activeDay`
- **THEN** panel 内 click-to-cancel MUST 只能触发 activeDay 撤单（broker 仅接受当日 trd_date）
- **AND** `cancelOrder(order_no, trd_date)` MUST 传 activeDay（`row.trd_date`）

### Requirement: 今日成交 panel（TodayTradesPanel 内嵌于 Trade.vue）

The system SHALL 提供 `client/src/components/trade/TodayTradesPanel.vue` 组件，作为
`Trade.vue` 右侧 sticky 列的下方面板，承载今日成交数据实时展示：

- **数据源**：`useHoldingsStore().trades`，Pinia 内存 + IDB write-through
- **范围过滤**（panel-local computed `todayTrades`）：
  - `trd_date === activeTrdDate`（仅当日）
  - `Number(trade_type) !== 1`（排除 cancel-fill，统计口径干净）
- **分页**：el-pagination 默认 20 行/页（与 TodayOrdersPanel 对称）
- **无撤单按钮**（trades 是终态历史，无可撤；与 history 语义一致）
- **panel 视觉**：同 `TodayOrdersPanel.vue` 结构

#### Scenario: panel 数据流（v13 嵌入模式）

- **WHEN** user 登录后打开 `/trade`
- **THEN** `TodayTradesPanel.todayTrades` MUST 渲染当日成交 (`trade_type !== 1`) 子集
- **AND** MUST NOT 发任何 HTTP 请求
- **AND** ws `trade_update` 来时 panel MUST 自动更新

#### Scenario: 成交金额本地计算

- **WHEN** panel 渲染 `price × volume` 列
- **THEN** MUST 用本地 `(Number(row.volume) || 0) * (Number(row.price) || 0)` 计算
- **AND** MUST NOT 引用 ws payload 的 `amount` 字段（与 holdings store 独立计算层一致）

### Requirement: Trade.vue 右侧双 panel 等分右列高度（v13）

The system SHALL 让 `Trade.vue` 右侧 `.trade-panels-col` 列内 `TodayOrdersPanel` 与 `TodayTradesPanel`
通过 `flex: 1 1 0; min-height: 0; overflow: hidden` 等分右列高度，避免 panel 内容短时下沿留白。

- `.trade-panels-col > * { flex: 1 1 0; min-height: 0; overflow: hidden }`
- 配合外层 `Trade.vue` `.trade-grid { flex: 1; min-height: 0 }` 形成完整 flex 链（详见 frontend capability "Trade.vue panel 上下填满"）

#### Scenario: 双 panel 等分右列

- **WHEN** viewport ≥ 1100px
- **THEN** 两个 panel 各占右列高度的 50%
- **AND** panel 内容短时下沿 MUST 不留白（el-empty 居中 + flex 撑满）

### Requirement: IDB write-through 行为（v12 + v13 复合 PK 重构）

The system SHALL 在以下时机写 IDB：

- **写时机**：
  - `bootstrap()` 完成 + Pinia ref 初始填充后，loop `saveOrder(order)` + `saveTrade(trade)` 逐行写
  - `applyOrderPush` / `applyTradePush` 每次合并后，调 `saveOrder(merged)` / `saveTrade(newTrade)` 写**单行**（O(1) idbPut）
- **IDB schema (v13 复合 PK)**：
  - DB version = 2, 2 个 object store: `orders` / `trades`
  - `orders`  key = `${trd_date}:${order_no}`              value = 单行 OrderOut
  - `trades`  key = `${trd_date}:${order_no}:${trade_id}` value = 单行 TradeOut
  - 镜像 server/tables/ 表类：Order/Trade PK 维度
- **读时机**：
  - `bootstrap()` 第 2 步：loadOrdersForDate / loadTradesForDate 走 idbGetAllKeys 扫描 + 前缀过滤
- **清时机**：
  - `bootstrap()` 检测到 `activeTrdDate !== IDB 中存在的 trd_date` → `clearDate(昨日的 trd_date)` 清理（同样走扫描）

#### Scenario: IDB 写成功（v13 单行写）

- **WHEN** `applyOrderPush` 完成 merge
- **THEN** IDB 中 `orders` store 的 `${trd_date}:${order_no}` 键立刻同步
- **AND** F5 后 `bootstrap` 读到 IDB 数据与 ws 增量合并后保持一致

#### Scenario: IDB 写异常不抛

- **WHEN** `saveOrder` / `saveTrade` 内 IDB put 抛错（quota exceeded / 浏览器隐私模式）
- **THEN** catch all + `console.warn('[IDB] saveOrder/saveTrade failed:')`
- **AND** Pinia ref 不动（数据完整）

#### Scenario: 跨日清 IDB

- **WHEN** 早上 09:00 bootstrap，`activeDay = 20260704`
- **AND** IDB.orders 仍有 `20260703:` 前缀的 key
- **THEN** `clearDate(20260703)` 清掉所有 `20260703:` 前缀的 key（orders + trades）
- **AND** 走正常 bootstrap 拉今日当日数据并存入 IDB

### Requirement: bootstrap 加载顺序契约（v12 详细化）

The system MUST 保证 IDB 命中时 Pinia 立刻有数据 + 用户看不到空白（详见 `frontend/spec.md` v12 修订的 `bootstrap` 顺序段）。

#### Scenario: F5 后 200ms 内显示当日委托

- **WHEN** user F5 后 200ms 内
- **THEN** `holdings.orders.length > 0`（来自 IDB 同步读）
- **AND** UI 不显示空态、显示加载 spinner 或直接表格

#### Scenario: IDB 缺失 → fallback 拉取

- **WHEN** IDB 中无 `activeDay` 键
- **THEN** bootstrap 走 `getOrders({ trdDate: activeDay })` 拉取当前 active 1 day 窗口
- **AND** 拉取成功后立刻写 IDB

### Requirement: 单 tab 与多 tab 行为（约束）

The system SHALL 接受多 tab 各自的 Pinia 内存态不同 —— IDB write-through 仅保证单 tab 内 page reload 数据连续，不保证跨 tab 同步。

#### Scenario: 多 tab 不竞争

- **WHEN** user 开 2 个 tab 同登录
- **THEN** IDB 是 last-write-wins（浏览器 IDB 自身并发模型）
- **AND** 2 tab 的 ws 各自独立收到 push，各自 merge 到本地 Pinia
- **AND** 不保证 2 tab 显示完全一致（同上一 explore 分析 §4.3）

### Requirement: ws push 同时写 Pinia + IDB 不阻塞 event loop

The system SHALL 确保 IDB 写是 fire-and-forget（异步），不阻塞 ws push 的 UI 更新。

#### Scenario: IDB put 100ms 延迟

- **WHEN** IDB put 耗时 100ms（罕见）
- **THEN** ws push handler 不 `await` IDB put
- **AND** UI 立刻反映新 push 数据
- **AND** IDB put 后台完成
