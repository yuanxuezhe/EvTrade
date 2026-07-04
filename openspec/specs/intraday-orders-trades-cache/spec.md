## Purpose

委托 / 成交 当日数据通过 Pinia + 浏览器 IDB write-through 持久化，无需重新拉取即可在 F5 / 重新打开 tab 后立即恢复（< 200ms）。positions / asset 不持久化（实时性 + 安全考虑）。

## Requirements

### Requirement: 当日委托 / 当日成交视图（v12 新增）

The system SHALL 提供两个独立路由承载当日委托 / 当日成交，数据**来自 Pinia 内存 + IDB 持久化**，不再走 `/api/orders` 或 `/api/trades` 拉取路径。

#### Scenario: TodayOrders.vue 数据流

- **WHEN** user 导航 `/today/orders`
- **AND** bootstrap 已完成（`holdings.bootstrapped === true`）
- **THEN** view 渲染 `useHoldingsStore().orders` 全数组
- **AND** 不发任何 HTTP 请求
- **AND** ws `order_update` 来时 `applyOrderPush` 自动 merge 到前端表

#### Scenario: TodayTrades.vue 数据流

- **WHEN** user 导航 `/today/trades`
- **THEN** 渲染 `useHoldingsStore().trades`，不发 HTTP 请求
- **AND** ws `trade_update` 来时 `applyTradePush` 自动 merge

### Requirement: IDB write-through 行为（v12 + v13 复合 PK 重构）

The system SHALL 在以下时机写 IDB：

- **写时机**：
  - `bootstrap()` 完成 + Pinia ref 初始填充后，loop `saveOrder(order)` + `saveTrade(trade)` 逐行写
  - `applyOrderPush` / `applyTradePush` 每次合并后，调 `saveOrder(merged)` / `saveTrade(newTrade)` 写**单行**（O(1) idbPut）
- **IDB schema (v13 复合 PK)**：
  - DB version = 2, 2 个 object store: `orders` / `trades`
  - `orders`  key = `${trd_date}:${order_no}`              value = 单行 OrderOut
  - `trades`  key = `${trd_date}:${order_no}:${trade_id}` value = 单行 TradeOut
  - 镜像 server/models/orm.py: Order/Trade PK 维度
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
