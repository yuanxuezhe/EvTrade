# strategy-order-design — 策略下单(母单)实盘下单

## Why

v125 将策略模块改为**纯回测**：删除 `POST /strategies/{id}/live` 端点、`/live` 前端入口、live 徽章，引擎侧 `strategy_exec` LiveRunner / `signal_consumer` / `/internal/run-task mode=live` 链路**完整保留**（v125 仅删 API 层）。这导致一个**业务断点**已经回测出 `best_params` 的策略无法启动实盘，量化用户的工作流断裂。

本 change 重建**实盘入口**，但**不复用** v125 删除前的旧 `/live` 端点形态，而是引入新的 `strategy_order` **母单**概念：

- **母单可重复启停**：用户对同一策略可多次启动/停止，参数每次启动时重新读 `strategy.best_params`（重启即用最新 best_params），多次运行的子单**累积**归因到同一母单，便于按策略/标的做交易归因审计。
- **参数对外不可见**：母单运行只传 `strategy_id`，实盘参数直接从 `strategy.best_params` 读取，**前端不展示、不修改**，与 v125 R5「他人公开策略的 best_params 不外露」原则一致。
- **子单归因到母单**：信号链路在 RabbitMQ payload 携带 `parent_task_id` + `strategy_name`（方案 B），`signal_consumer` 用 `parent_task_id` 作 `orders.task_id`、`strategy_name` 作 `user_def`、`strategy_type=2`，与现有 v66 快速做T 单（`strategy_type=1`）和普通单（`strategy_type=0`）三分明确区分。
- **母单独立页 + 4 面板**：与 T0Trade 互不串扰（新 `strategy_type=2` 维度 + T0Trade 防御过滤 `strategy_type !== 2` 双向防撞号）。

不做（YAGNI，详见设计文档 §8）：母单资金/持仓/盈亏聚合、下单量/资金管理、策略克隆、风控、DELETE 硬删（close 保审计）。

## What Changes

### 新增

- **新表 `strategy_order`**（母单）：自增 `id` + `UNIQUE(task_id)`（`order_no_seq` 的 `strategy_order` 生成器）+ `user_id` + `strategy_id` + `stock_code`（冗余展示/过滤）+ `status`（`stopped`/`running`/`closed`）+ `active_task_id`（当前 live `strategy_task.id`）+ `run_count` + `last_started_at` / `last_stopped_at` / `closed_at` + 时间戳。`server/tables/strategy_order.py` 由 `tables-codegen` 生成。
- **新 `order_no_seq` 生成器** `strategy_order`：`INSERT IGNORE INTO order_no_seq(seq_name, last_value) VALUES ('strategy_order', 0)`（迁移幂等）。
- **新 `server/services/script_strategy/strategy_orders.py`**（服务层）+ **`server/api/script_strategy/strategy_orders.py`**（REST 层）：6 个端点（建/列表/详情/启动/停止/关闭），统一入口 `server/services/script_strategy/__init__.py` 与 `server/api/script_strategy/__init__.py` 导出。
- **新 schema**：`StrategyOrderCreate` / `StrategyOrderOut` / `StartStopResponse` 追加到 `server/api/script_strategy/schemas.py`。
- **新前端页** `client/src/views/StrategyOrder.vue`，4 面板独立页：策略下单 / 行情面板（复用 `QuotePanel.vue`）/ 策略母单 / 委托子单。
- **新 `client/src/api/script_strategy.js` 端点封装** `strategyOrders.*`。

### 修改

- **`orders.strategy_type` 列扩到 2**：`server/api/orders/schemas.py` 的 `strategy_type: Literal[0, 1]` → `Literal[0, 1, 2]`；`OrderOut.strategy_type` 注释同步；`server/models/orm.py` + `server/schema.yml` 的 COMMENT 更新（0=普通单 / 1=快速做T / **2=策略下单**），列类型 TINYINT 不变（迁移 COMMENT-only，幂等）。
- **`server/services/strategy/signal_consumer.py`**：BUY/SELL 下单请求的 `task_id` 由 `payload.get("task_id")` 改 `payload.get("parent_task_id")`，`user_def` 由空字符串改 `payload.get("strategy_name")`，`strategy_type` 由 0 改 2。
- **`client/src/views/T0Trade.vue`**：委托过滤（≈470 行）加 `strategy_type !== 2` 条件，与策略单按 `strategy_type` 互斥。
- **`client/src/components/layout/NavBar.vue`**（桌面）：加「策略下单」入口 → `/strategy-order`。
- **迁移脚本**（幂等，`INFORMATION_SCHEMA` 检查）：
  - `2026-08-11-add-strategy-order.py`：建 `strategy_order` 表 + `order_no_seq` 加 `strategy_order` 生成器 + `orders.strategy_type` COMMENT 更新。
- **`strategy_exec` 服务（外部服务，需同步改）**：
  - `signal/types.py`：`Signal` 加 `parent_task_id: Optional[int] = None` + `strategy_name: str = ""`；`signal_to_payload` 用 `asdict` 自动序列化无需改。
  - `engines/backtrader/adapter.py`：`_set_task_meta` 加 2 个默认参数；`_publish` 构造 Signal 带上。
  - `engines/backtrader/live.py`：`LiveRunner.__init__` + `start_live_runner` 透传。
  - `api/internal.py`：`RunTaskRequest` 加 `parent_task_id` + `strategy_name`，live 分支透传。
  - 回测路径签名兼容（默认值 `None`/`""`），不影响 v125 既有的纯回测行为。
- **`openspec/specs/strategy/spec.md`**：新增 **REQ-STRAT-020: 策略母单与实盘下单 (v126, 2026-08-11)**，含数据模型 / 信号链路 / 6 端点 / 权限 / 前端 / 4 个 Scenario。
- **`openspec/specs/data-model/spec.md`**：§14 `orders.strategy_type` 列表追加 `2=策略下单`。
- **`openspec/specs/strategy-exec/spec.md`**：REQ-SE-005（Signal 类型）加 `parent_task_id` + `strategy_name` 字段；REQ-SE-008（LiveRunner）说明母单透传。

### 删除

（**无**。v125 已删 `/live` 端点；本 change 不回滚、不重复删）

## Capabilities

### New Capabilities

（**无**；本 change 落在既有 `data-model` / `strategy` / `strategy-exec` / `trading` / `frontend` 五类能力上）

### Modified Capabilities

- **`data-model`**：新增 `strategy_order` 表；`order_no_seq` 新增 `strategy_order` 生成器；`orders.strategy_type` COMMENT 扩展（值集合 0/1→0/1/2，列类型不变）。
- **`strategy`**：新增 REQ-STRAT-020 — 母单 6 端点、状态机、权限（继承 REQ-STRAT-019 owner/admin 矩阵 + best_params 门禁 + 他人公开不可下单）。
- **`strategy-exec`**：Signal payload 加 `parent_task_id` + `strategy_name`；LiveRunner / `_set_task_meta` / `start_live_runner` / `RunTaskRequest` 透传；回测路径签名兼容。
- **`trading`**：`PlaceOrderRequest.strategy_type` 范围 0/1→0/1/2；`OrderOut.strategy_type` 注释同步。
- **`frontend`**：新 `StrategyOrder.vue` 4 面板页；NavBar 入口；T0Trade 委托过滤加 `strategy_type !== 2` 互斥。

## Impact

- **DB 迁移**（1 个脚本）：建 `strategy_order` 表（7 列 + 3 索引）；`order_no_seq` 加 `strategy_order` 行；`orders.strategy_type` COMMENT 更新。
- **后端**：`server/api/script_strategy/{schemas.py, strategy_orders.py, __init__.py}`、`server/services/script_strategy/{strategy_orders.py, __init__.py}`、`server/services/strategy/signal_consumer.py`、`server/api/orders/schemas.py`、`server/tables/strategy_order.py`（tables-codegen）。
- **strategy_exec**（外部服务，需同步改 4 个文件）：`signal/types.py`、`engines/backtrader/{adapter.py, live.py}`、`api/internal.py`。
- **前端**：`client/src/views/StrategyOrder.vue`（新建）+ `client/src/components/strategy/`（新增 4 面板组件，沿用 `QuotePanel.vue`）+ `client/src/api/script_strategy.js` + `client/src/views/T0Trade.vue` + `client/src/components/layout/NavBar.vue` + `client/src/router/index.js`（加路由）。
- **测试**：`tests/server/strategy/`（母单状态机 + 权限 + best_params 门禁 + task_id 来自序号生成器）+ `tests/server/strategy/test_signal_consumer.py`（BUY/SELL payload 映射）+ 迁移幂等用例 + 前端组件测试（StrategyOrder + T0Trade 互斥）。

## 风险与决策

> 本节列出**已识别但本 change 不修复**的设计层面风险，**供未来 review 决策参考**，不阻塞实施。

### 风险 1: `task_id` 撞号空间未隔离

- **现状**：`signal_consumer` 用 `payload.parent_task_id` 作 `orders.task_id`，**与 v125 backtest `strategy_task.id` 共用同一 `orders.task_id` 序号空间**。设计文档 §3 已注明此方案 B 复用现有 `orders.task_id` 字段（最小改动）。
- **风险**：若某回测 `strategy_task.id` 与某母单 `strategy_order.task_id` 数值相同（母单 `task_id` 由 `order_no_seq.strategy_order` 生成，起始 0；backtest `strategy_task.id` 是 DB 自增，两个生成器**理论上可撞号**，虽然实际并发场景下概率极低），子单会归因到错的 task。
- **本 change 决策**：**不处理**，按已提交设计走。实施时只在测试覆盖中明确「母单 task_id 来自 `next_seq('strategy_order')`」与「回测 task_id 来自 strategy_task.id 自增」两条路径不交叉。
- **未来缓解方案**（任选其一，需独立 change）：
  1. 母单 `task_id` 用独立段（如 `next_seq` 起始 1_000_000，避开 strategy_task 自增范围），`signal_consumer` 落库前 if `parent_task_id < 1_000_000` 视为异常丢弃。
  2. `orders.task_id` + `orders.strategy_type` 联合索引，前端过滤/后端查询全部带 `strategy_type` 区分（已在 T0Trade + StrategyOrder 双向防御过滤中实现首步）。
  3. 母单 `task_id` 用 UUID 字符串（schema 需从 INT 改 VARCHAR(36) 破坏性更大）。

### 风险 2: `signal_consumer` 假设 payload 必有 `parent_task_id`（方案 B 强约定）

- **现状**：方案 B 强假设 v126 之后所有 live 信号 payload 必带 `parent_task_id` + `strategy_name`（v125 之后只剩母单路径触发 live）。
- **风险**：若有人未来不经母单（如脚本直接调 `/internal/run-task mode=live`）触发信号，`parent_task_id=None` 会被 `signal_consumer` 视为"回测路径"**跳过**（`parent_task_id or None` 退化回 `None` → 走回测分支）→ 静默丢失信号，**不报错**。
- **本 change 决策**：**不处理**。策略模块 v125 之后唯一 live 入口就是母单启动；脚本直调 `/internal/run-task` 不在合法路径上。`signal_consumer` 加防御日志（`parent_task_id is None` 且 `mode=='live'` 时 WARN）即可，但不纳入本 change。

### 风险 3: `run_count` 累加与 `active_task_id` 残留

- **现状**：母单 stop 时仅置 `active_task_id=NULL` + `status=stopped`，`strategy_task` 行**不删**（v125 约定 task 保审计）。
- **风险**：若 `signal_consumer` 收到某个 `parent_task_id` 对应的延迟信号（live runner 异步停止中），仍会下子单 → `orders.task_id` 指向已 stop 的母单。前端「策略母单」面板的「子单数」COUNT 会继续涨，造成认知偏差。
- **本 change 决策**：**不处理**。live runner 停止有收敛机制（v120 已实现），残余信号窗口小；前端不做实时反查。子单累积归因是设计本意，不视为 bug。

## 关联变更

- 承接：v125 `REQ-STRAT-019` 策略可见性/权限矩阵（2026-08-11）— best_params 门禁 + 他人公开 best_params 不外露原则
- 承接：v125 `REQ-STRAT-019` §「实盘/黑盒跟随移出本模块(Part 2 策略下单另行设计)」— 本 change 即 Part 2
- 关联：v124 `REQ-STRAT-018` 批次重测 — 母单启动实盘仍走 `strategy_task` 批次链路（`mode='live'` 1 行 task）
- 关联：v122 `strategy-params-sweep-best-live` — `strategy.best_params` 在本 change 中是**实盘门禁**与**参数源**
- 设计文档：`docs/superpowers/specs/2026-08-11-strategy-order-design.md`（v126, 2026-08-11）
