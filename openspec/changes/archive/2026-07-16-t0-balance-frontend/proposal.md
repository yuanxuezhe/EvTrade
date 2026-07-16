# Proposal: T0 配平切换为前端计算 + 复用下单接口

## Why

v55 实现的"一键配平"通过 `POST /api/t0-tasks/{id}/balance` 走服务端 RPC：

- 后端查该 task 下所有订单 → 计算净敞口 → 调 xtquant 报单
- 缺点：① round-trip 多 ② 实时性差（用户点按钮才知差值） ③ 多一层 API 路径

用户要求替换为：

- **前端**读 `holdings.orders`（实时推送）→ 算 (买单量 - 卖单量) 差 → 调 `api.placeOrder` 下市价单
- **删除** `POST /api/t0-tasks/{id}/balance` 整个调用链（endpoint + 4 个前端调用点）
- 同步新增**主页面上下分区** —— 上半任务表 + 下半实时委托表，按推送实时算"需补 X 股"

## What Changes

### 删除
- **后端** `server/api/t0_tasks.py` 的 `@router.post("/{task_id}/balance")` 整个 endpoint（约 30 行）
- **前端** `client/src/api/t0_tasks.js` 的 `balance(taskId, dryRun)` 方法（约 10 行）
- **前端** `client/src/stores/t0_tasks.js` 的 `balanceTask(taskId)` action + export
- **前端** `client/src/components/trade/T0TaskDetail.vue` 的 `onBalance` 函数（不再调用 store.balanceTask）

### 新增 / 改造
- **前端** `client/src/views/T0Trade.vue` 上下两区布局：
  - **上半**：现有 8 列 task 表（v55）+ 主表操作列"配平"按钮改造为前端算 + 下市价单
  - **下半**：**实时委托表** —— 按 `selectedTaskId` 过滤 `holdings.orders`，7 列（委托号/方向/价格/数量/状态/下单时间/备注）
- **前端** `client/src/views/T0Trade.vue` 新增 `onBalanceTask` 实现：
  1. 从 `holdingsStore.orders.filter(o => o.task_id === selectedTaskId)` 拿所有任务订单
  2. 筛选已成交 (`trade.trd_status === '51'`) 的 status，对买单求和 `volume`，对卖单求和 `volume`
  3. 计算 diff = 已成交买单量 - 已成交卖单量
     - diff > 0 → 多买了 → 反向 = `SELL` (卖)
     - diff < 0 → 多卖了 → 反向 = `BUY` (买)
  4. 复用 `useT0OrderSubmit` composable 下市价单（`price_type: 44`，`volume = |diff|`）
- **前端** 主表"配平"按钮：差值=0 时 disabled，按钮文案动态显示"差 X 股，买/卖"

### 边界
- 沿用 v54 `useT0OrderSubmit` composable + 价格类型映射
- 不引入新的委托 store（`holdingsStore.orders` 是唯一源，v8 架构）
- 旧的 `POST /balance` endpoint **保留 disabled** 或**彻底删除**：建议**删除**（用户明确说"去掉这个接口"），但**注意是测试环境**——失败可 git revert

## Impact

| 受影响系统 | 改动量 | 风险 |
|---|---|---|
| 后端 `t0_tasks` API | 删 ~30 行 | 低（前端再调用直接 404 即可发现） |
| 前端 t0_tasks store/api | 删 ~30 行 | 低 |
| 前端 T0Trade view | +120 / -30 行 | 中（UI 重构 + 新增委托表） |
| 前端 T0TaskDetail | 删 ~10 行 | 低（同步移除"配平"按钮回调） |
| OpenSpec | 新增 REQ-FE-231 | 低 |

## Alternatives Considered

### 方案 A（采纳）
前文描述。

### 方案 B：保留 `GET /balance` dryRun 作实时提示
- 优点：保留 dry-run 流（前端可展示服务端计算的 diff）
- 缺点：还是多一层 RPC，违反用户"纯前端算"诉求

### 方案 C：完全废弃前端算，全部让用户自己点买单/卖单
- 优点：实现最简
- 缺点：体验差，需用户心算

## References
- `server/api/t0_tasks.py:336` 现存 endpoint
- `client/src/stores/t0_tasks.js:120` 现存 balanceTask
- `client/src/views/T0Trade.vue:312` 现存 onBalanceTask（后端模式）
- v54 复用：`client/src/composables/useT0OrderSubmit.js:25` submitOrder 接受 `taskId` 参数
- v8 架构：所有委托/成交走 `holdingsStore.orders/trades` 唯一源，由 `applyOrderPush`/`applyTradePush` 守门
