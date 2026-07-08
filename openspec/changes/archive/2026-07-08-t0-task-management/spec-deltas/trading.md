## ADDED Requirements

### Requirement: REQ-TRADE-013 T0Task 一等公民实体（v18）

平台 MUST 把"做 T 任务"作为一等公民实体持久化，区别于 `Order.user_def = 'T0'` 的隐式标签：

- **`T0Task`** 表字段：
  - `id` int PK auto_increment
  - `user_id` int NOT NULL — owner
  - `stock_code` varchar(16) NOT NULL
  - `base_volume` int NOT NULL DEFAULT 0 — 底仓量（"保留部分底仓"语义）
  - `target_volume` int NOT NULL DEFAULT 0 — 目标开仓量（区别于现仓位的净增量）
  - `coefficient` float NOT NULL DEFAULT 1.0 — 复用 REQ-TRADE-005 配平系数
  - `status` enum('active','closed','archived') NOT NULL DEFAULT 'active'
  - `note` varchar(255) — 用户备注
  - `created_at` / `closed_at` datetime
  - `created_trd_date` varchar(8) — 创建日交易日（业务字段，不用创建时间倒推）

- **Order 表加 `task_id`**：
  - `task_id` int NULL — 可选 FK → `t0_tasks.id`
  - **与 `user_def = 'T0'` 共存**：新建 task 后的单同时写 `user_def='T0'` AND `task_id=<id>`；无 task 的旧 T0 单 `task_id IS NULL` + `user_def='T0'`
  - 加索引 `ix_orders_task_id`

- **创建规则**：
  - `base_volume` 必须 `>= 0`
  - `target_volume` 可以为负数（净减仓目标）
  - `base_volume + target_volume` = 任务终态持仓目标

#### Scenario: 基于现仓位建任务

- **GIVEN** 现仓位 `Position{stock_code: '600519.SH', vol: 1000, cost_price: 1500}`
- **WHEN** `POST /api/t0-tasks { stock_code: '600519.SH', base_volume: 1000, target_volume: 2000 }`
- **THEN** 创建 task `id=5, base_volume=1000, target_volume=2000, status='active'`
- **AND** task 净敞口初值 = 0（建任务时不立即建仓位；现仓位归到 base_volume）

#### Scenario: 0 持仓建任务

- **GIVEN** `Position{stock_code: '002594.SH'}` 不存在
- **WHEN** `POST /api/t0-tasks { stock_code: '002594.SH', base_volume: 0, target_volume: 1000 }`
- **THEN** 创建 task `base_volume=0, target_volume=1000, status='active'`
- **AND** 用户后续手动买入 1000 股 → 归到该 task

#### Scenario: 旧 T0 单不带 task_id

- **GIVEN** 已有 `Order{user_def: 'T0', task_id: NULL}`
- **WHEN** 跑 `/api/t0-stats/600519.SH?t0_only=true`
- **THEN** 仍然包含此单（向后兼容：旧 path 走 user_def 聚合）
- **AND** `/api/t0-tasks/{id}/stats` 不包含此单（task 维度只看 task_id 关联单）

#### Scenario: task_id NOT NULL constraint

- **WHEN** migration `add-t0-tasks.py` 跑
- **THEN** 表创建幂等（`CREATE TABLE IF NOT EXISTS t0_tasks`）
- **AND** `ALTER TABLE orders ADD COLUMN task_id INT NULL` 幂等（检测列存在则跳过）
- **AND** `CREATE INDEX ix_orders_task_id ON orders(task_id)` 幂等

### Requirement: REQ-TRADE-014 T0Task CRUD API（v18）

后端 MUST 暴露以下 REST 端点：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/t0-tasks` | `POST` | 创建任务 |
| `/api/t0-tasks` | `GET` | 列表（支持 `?status=active` / `?stock_code=` / `?days=30`） |
| `/api/t0-tasks/{id}` | `GET` | 详情（含统计 + 当日净敞口） |
| `/api/t0-tasks/{id}` | `PATCH` | 改 note / coefficient / status（`status` 仅允许 `active ↔ closed`，归档用 DELETE） |
| `/api/t0-tasks/{id}` | `DELETE` | 仅 `archived` 状态可删（防误操作） |
| `/api/t0-tasks/{id}/balance` | `POST` | 一键配平（按 task 净敞口 - base_volume） |
| `/api/t0-tasks/{id}/close` | `POST` | 关任务（强制配平净敞口 → 改 status=closed → 设 closed_at） |
| `/api/t0-tasks/{id}/stats` | `GET` | 统计（已实现 + 未实现 + 累计天数 + 胜率） |

#### Scenario: 创建任务鉴权

- **WHEN** 非 `trader` / `admin` 角色 `POST /api/t0-tasks`
- **THEN** MUST 返回 `403`
- **AND** admin 可看所有 user_id 的 task；trader 只能看自己的

#### Scenario: balance 配平公式

- **GIVEN** task `id=5, base_volume=1000, target_volume=2000`，已成交 task 内 `buy_vol=2000, sell_vol=300`
- **WHEN** `POST /api/t0-tasks/5/balance { coefficient: 1.0 }`
- **THEN** `task_net_volume = buy_vol - sell_vol = 1700`
- **AND** `task_target = base_volume + target_volume = 3000`
- **AND** `balance_volume = task_target - (task_net_volume + current_position_vol)`（按现仓位算缺口）
- **AND** 若 `balance_volume > 0` → 提交买单 `volume=round_to_lot(balance_volume * coefficient, 'BUY')`；否则提交卖单
- **AND** 提交的单 MUST 写 `task_id=5` AND `user_def='T0'`

#### Scenario: balance 资金/持仓前置校验

- **WHEN** `balance_volume > 0` 但 `asset.cash < balance_volume * price`
- **THEN** MUST 拒绝，返回 `409 Conflict`，body `{detail: '资金不足, 需 ¥X 现有 ¥X'}`
- **WHEN** `balance_volume < 0` 但 `Position{stock_code}.avl_vol < |balance_volume|`
- **THEN** MUST 拒绝，返回 `409 Conflict`，body `{detail: '持仓不足, 缺 X 股'}`
- **AND** 与 REQ-TRADE-010 前端 disabled 校验同口径

#### Scenario: close 强制配平

- **WHEN** `POST /api/t0-tasks/5/close`
- **THEN** 先按 REQ-TRADE-014 balance 逻辑配平到 `base_volume`（**保留底仓**）
- **AND** 配平成功 → `status='closed'`，`closed_at=now()`
- **AND** 配平失败 → `status` 不变，返回错误，调用方需手动处理

#### Scenario: delete 仅 archived 可删

- **WHEN** `DELETE /api/t0-tasks/5` 且 `status='active'`
- **THEN** MUST 拒绝，返回 `409 Conflict`
- **WHEN** `DELETE /api/t0-tasks/5` 且 `status='archived'`
- **THEN** 删除该 task 记录（**不级联删除 orders**，保留审计）

#### Scenario: 列表按状态过滤

- **WHEN** `GET /api/t0-tasks?status=active`
- **THEN** MUST 只返 `status='active'` 的 task
- **AND** 按 `created_at DESC` 排序
- **AND** 每行附带 `summary`：`{task_net_volume, realized_pnl, unrealized_pnl, position_vol}`

### Requirement: REQ-TRADE-015 T0Task 统计维度（v18）

`GET /api/t0-tasks/{id}/stats` MUST 返回：

```json
{
  "task": { "id": 5, "stock_code": "...", "status": "active", "base_volume": 1000 },
  "summary": {
    "task_net_volume": 700,           // task 内 buy_vol - sell_vol（不含建任务前现仓）
    "position_vol": 1700,              // 当前持仓（含 task 外底仓）
    "task_attributed_vol": 700,       // = task_net_volume, 任务贡献
    "realized_pnl": 1200.0,            // task 内卖出 pnl - 卖 fee - 卖 tax
    "unrealized_pnl": 350.0,          // (last_price - cost_basis) * task_net_volume
    "commission_total": 50.0,
    "stamp_tax_total": 80.0,
    "trade_count": 12,
    "order_count": 8,
    "first_trd_date": "20260701",     // task 内最早交易日
    "last_trd_date": "20260708",
    "trading_days": 6,
    "winning_days": 4,                 // 当日 realized_pnl > 0 的天数
    "win_rate": 0.667
  },
  "daily": [
    { "trd_date": "20260701", "buy_vol": 500, "sell_vol": 0, "net_vol": 500, "realized_pnl": 0, "cum_pnl": 0 },
    { "trd_date": "20260702", "buy_vol": 0, "sell_vol": 300, "net_vol": -300, "realized_pnl": 600, "cum_pnl": 600 },
    ...
  ],
  "by_stock": [...]                   // 任务都是 1 个 stock_code，但保持 schema 对齐 REQ-TRADE-006
}
```

#### Scenario: realized_pnl 计算口径

- **WHEN** task 内卖单 `price=15, volume=300`，task 内买单均价 `cost_basis=14`
- **THEN** `realized_pnl = (15 - 14) * 300 - commission - stamp_tax`
- **AND** `commission = round(4500 * fee_cfg.commission_rate, 2)`；`stamp_tax = round(4500 * fee_cfg.stamp_tax_rate, 2)`
- **AND** 复用 `services/t0/pnl.py::calc_realized_pnl`

#### Scenario: unrealized_pnl 计算口径

- **WHEN** task 内 `task_net_volume=700, cost_basis=14, last_price=14.5`
- **THEN** `unrealized_pnl = (14.5 - 14) * 700 = 350`
- **AND** `last_price` 走 `useQuoteStore().getLastPrice(stock_code)`，无 quote 时走 `Position.cost_price` 兜底
- **AND** `unrealized_pnl` 不扣预期费用（前端展示时另算 "扣费后未实现"）

#### Scenario: winning_days 统计

- **WHEN** task 跨 6 个交易日，每日 realized_pnl = [+200, -100, +300, 0, +50, -30]
- **THEN** `winning_days = 4`（包含 0；明确大于 0 才算胜）
- **AND** `trading_days = 6`
- **AND** `win_rate = 4 / 6 ≈ 0.667`

#### Scenario: 无关联单

- **WHEN** task 建完无任何成交
- **THEN** MUST 返回 `task_net_volume=0, realized_pnl=0, unrealized_pnl=0, trading_days=0`
- **AND** 不抛错，`daily=[]`

### Requirement: REQ-TRADE-016 T0Task UI 集成（v18）

`T0Trade.vue` MUST 在顶部集成 task 切换：

- **当前 task 下拉**：展示 `active` 状态任务列表（按更新时间倒序）
- **无 task 模式**：默认选 "未指定 task"（下单不带 task_id，仅 user_def='T0'）
- **建任务按钮**：打开 `<T0TaskCreateDialog>`，从 `usePositionStore().positions` 选 stock_code → 弹输入 `base_volume / target_volume / note`
- **任务详情抽屉**：点击 task 行 → 打开 `<T0TaskDetail>` 抽屉：
  - 顶部：摘要卡片（净敞口 / 已实现 / 未实现 / 胜率 / 累计天数）
  - 中部：每日 PnL 折线图（用现有 `<T0ChartGeometry>` / ECharts）
  - 下部：操作按钮 `[一键配平] [关任务] [编辑]`
- **下单带 task_id**：`useT0OrderSubmit.submitOrder(...)` MUST 在选了 task 时附带 `task_id`

#### Scenario: 未选 task 下单

- **WHEN** 用户当前下拉 = "未指定 task"
- **AND** 提交买单 `{ stock_code: '600519.SH', volume: 100, price: 15 }`
- **THEN** 后端收到 `Order{user_def='T0', task_id=NULL}`
- **AND** 与 v17 行为完全一致（向后兼容）

#### Scenario: 选 task 下单

- **WHEN** 用户当前下拉 = task id=5
- **AND** 提交买单
- **THEN** 后端收到 `Order{user_def='T0', task_id=5}`

#### Scenario: 任务详情抽屉

- **WHEN** 点击 task 行
- **THEN** 抽屉滑入，宽度 480px
- **AND** 加载 `/api/t0-tasks/{id}/stats` 显示摘要 + 每日 pnl 图表
- **AND** 失败重试 1 次后弹 ElMessage.error

#### Scenario: 建任务对话框

- **WHEN** 用户点 `[+ 新建任务]` → 选 stock `002594.SH`
- **AND** 提交 `{ base_volume: 0, target_volume: 1000, note: '测试建任务' }`
- **THEN** 后端 `POST /api/t0-tasks` 返回 `{id: 6, ...}`
- **AND** 前端下拉自动切换到新 task
- **AND** 弹 ElMessage.success "任务创建成功"

### Requirement: REQ-TRADE-017 T0Task 跨日配平语义（v18）

"跨多日也能迅速配平" 的核心是 task 净敞口跨日累加：

- **Task 净敞口定义**：`task_net_volume = Σ(buy_vol) - Σ(sell_vol)` for orders where `task_id=X` AND `trd_date IN (created_trd_date, today]`
- **配平缺口公式**：
  ```
  position_vol = Position{stock_code}.vol（当前全部持仓，含 task 外底仓）
  target_position = base_volume + target_volume
  gap = target_position - position_vol
  balance_volume = round_to_lot(gap * coefficient)
  ```
- **正向 gap**（target > current）→ 提交买单
- **负向 gap**（target < current）→ 提交卖单
- **跨日累加**：每次配平提交的单都归到 task 下，下次配平时已计入

#### Scenario: 跨日累加净敞口

- **GIVEN** task `id=5, base_volume=1000, target_volume=2000, status='active'`
- **AND** T1 成交 `buy=500, sell=0` → `task_net_volume=500`
- **AND** T2 成交 `buy=0, sell=200` → `task_net_volume=300`
- **AND** T3 当前 `Position.vol=1300`（含 task 外 1000）
- **WHEN** `POST /api/t0-tasks/5/balance`
- **THEN** `position_vol=1300, target_position=3000, gap=+1700`
- **AND** 提交买单 `volume=round_to_lot(1700, 'BUY')=1700`（A 股整手）

#### Scenario: 配平保留底仓

- **GIVEN** task `id=5, base_volume=1000, target_volume=0, status='active'`
- **AND** 当前 `Position.vol=2000`（1500 task 内买 + 500 task 外 + 1000 base 不动）
- **WHEN** `POST /api/t0-tasks/5/balance { auto_close: false }`
- **THEN** `target_position = 1000 + 0 = 1000`
- **AND** `gap = 1000 - 2000 = -1000`
- **AND** 提交卖单 `volume=round_to_lot(1000, 'SELL')=1000`
- **AND** 配平后 `Position.vol=1000` = **底仓被保留**

#### Scenario: 跨多日 task 自动续命

- **GIVEN** task 创建于 T1，跨 T1/T2/T3/T4 共 4 个交易日
- **WHEN** 跨 4 日仍未关
- **THEN** 状态保持 `active`，`last_trd_date` 自动更新
- **AND** `trading_days = 4`（统计累计天数）

### Requirement: REQ-TRADE-018 整体做 T 收益 + 单券做 T 收益视图（v18）

新组件 `<T0TaskOverview>` 展示两层收益：

- **整体做T收益（cross-task summary）**：
  - 数据：`/api/t0-tasks?status=active` + `/api/t0-tasks?status=closed&days=30` 聚合
  - 卡片：累计 realized_pnl / 未实现 pnl / 总手续费 / 总印花税 / 累计天数 / 总胜率 / 活跃 task 数
- **单券做T收益（per-stock summary）**：
  - 数据：服务端聚合 `SELECT stock_code, SUM(realized_pnl), SUM(unrealized_pnl) ... GROUP BY stock_code` 走 task 维度
  - 卡片：每只券一行（stock_code / 已实现 / 未实现 / 净敞口 / task 数 / 累计天数）

#### Scenario: 整体视图

- **WHEN** 用户访问 `/t0-trade` 顶部
- **THEN** 显示 5 个 metric pill（沿用 REQ-TRADE-013 quota frame 风格）：
  - 累计已实现 = SUM(task.realized_pnl) for all tasks (active + closed last 30d)
  - 累计未实现 = SUM(task.unrealized_pnl) for active tasks
  - 活跃 task 数 = COUNT(where status='active')
  - 累计手续费 = SUM(task.commission_total) for closed last 30d
  - 胜率 = AVG(task.win_rate) for closed last 30d

#### Scenario: 单券视图

- **WHEN** 用户切到 "单券视角"
- **THEN** 列出所有有 task 的 stock_code：
  ```
  600519.SH  累计¥1200  未实现¥350  净+700  3 task  6日
  002594.SH  累计¥-200  未实现¥0    净 0    1 task  2日
  ...
  ```
- **AND** 点击行 → 跳到该 stock_code 的 task 列表

#### Scenario: 兼容旧 user_def='T0' 视角

- **WHEN** 用户没有建任何 task，但有 user_def='T0' 的旧单
- **THEN** `<T0TaskOverview>` 显示 "暂无 task，但有 X 笔历史 T0 单"
- **AND** 给出 "导入为 task" 按钮 → 把旧单按 stock_code 分组建 task