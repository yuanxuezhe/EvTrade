# strategy — 策略交易引擎（网格引擎已下线）

> **网格引擎下线（2026-08-10，commit `aa70dae`）**：REQ-STRAT-001~013（regime/grid 网格策略引擎）代码已彻底删除（后端 `api/strategy/` + `services/strategy/` 死代码 + `tables/strategy*.py`；前端 `StrategyTrade.vue` / `stores/strategy.js` / `api/strategy.js` / `strategy_update` WS 频道；DB DROP 4 张表）。本节保留为**历史正文**，不再是现行契约。
>
> **现行策略形态**：**脚本策略**（REQ-STRAT-014~017），引擎在独立服务 `strategy_exec/`（见 [`strategy-exec/spec.md`](../strategy-exec/spec.md)）。
>
> 📖 **DB schema** 详见 [`data-model/spec.md`](../data-model/spec.md)（`strategy_script` / `strategy_script_audit` / `strategy_task`）
> 📖 **REST 契约**：脚本策略端点见本 spec REQ-STRAT-015（`/api/script-strategy/*`）

## Purpose

（网格引擎 Purpose 已随 `aa70dae` 下线。现行：见下方 **Script-Strategy 模块** 一节）

~~为单只标的配置**多档「参数集 (regime)」**，按实时行情**量价标志 (flags)** 自动切换参数集 + 按当前 regime 的网格配置自动下单。~~

## Requirements

> ### 🗑️ REQ-STRAT-001 ~ REQ-STRAT-013：已删除（2026-08-10 grid-engine-removal）
>
> 以下 13 个 Requirement 描述**旧网格策略引擎**（regime/grid），已随 commit `aa70dae` 从代码库删除：
> 端点（`/api/strategy/*`）、引擎（`services/strategy/engine.py`）、4 张表（strategy / strategy_regime / strategy_grid / strategy_audit）、前端（`StrategyTrade.vue` / `strategy_update` WS 频道）全部下线。
>
> **保留历史正文的目的**：spec 演进史是"为什么这样决策"的证据（同 `docs/specs-history/` 思路）。阅读时请当作**已删除契约**，勿当作现行行为。

### REQ-STRAT-001: 策略 CRUD（已删除）

- `POST /api/strategy` — 新建（含嵌套 regimes + grids）
- `GET /api/strategy` — 列表，可按 `status` / `type` 过滤
- `GET /api/strategy/{id}` — 详情（含嵌套 regimes + grids）
- `PUT /api/strategy/{id}` — 全量替换嵌套结构
- `DELETE /api/strategy/{id}` — 级联删除 regimes / grids / audits
- 仅 `stock_code` / `type` / `reference_price` / `base_volume` / `note` / `regimes` 字段持久化；`status` 由控制接口变更

### REQ-STRAT-002: 9 种 flag 注册表（v1 硬编码）

| code | 名称 | 类别 | 检测逻辑 |
|---|---|---|---|
| `ma_bullish` | 均线多头 | trend | MA5 > MA10 > MA20 |
| `ma_bearish` | 均线空头 | trend | MA5 < MA10 < MA20 |
| `rsi_overbought` | RSI 超买 | oscillator | RSI(6) ≥ 70 |
| `rsi_oversold` | RSI 超卖 | oscillator | RSI(6) ≤ 30 |
| `vol_breakout` | 量能突破 | volume | 当根成交量 ≥ 2 × 过去 20 根均量 |
| `price_change_up` | 涨幅 ≥ +1% | price | (last - prev) / prev ≥ 0.01 |
| `price_change_down` | 跌幅 ≤ -1% | price | (last - prev) / prev ≤ -0.01 |
| `macd_golden_cross` | MACD 金叉 | oscillator | DIF 上穿 DEA |
| `macd_death_cross` | MACD 死叉 | oscillator | DIF 下穿 DEA |

- `GET /api/strategy/flags` — 返注册表（不受灰度门控；前端下拉选择源数据）
- buffer 不足（< 100 tick）或 `prev_close` 缺失 → 对应 flag 静默跳过，不抛错

### REQ-STRAT-003: 4 张 ORM 表

- `Strategy` — id / stock_code / type / status / reference_price / base_volume / note / created_at / updated_at
  - `type VARCHAR(16) NOT NULL DEFAULT 'general'`（`general` / `t0`）
  - 索引 `ix_strategy_type` on `type`（T0 端点 JOIN 过滤）
- `StrategyRegime` — id / strategy_id(FK) / name / priority / required_flags(JSON) / exclude_flags(JSON) / base_volume / clear_position / enabled
- `StrategyGrid` — id / regime_id(FK) / direction / step_offset / trigger_price / volume / max_fires / fired_count / enabled / priority
- `StrategyAudit` — id / strategy_id(FK) / regime_id / trd_date / trigger_type / flags_active(JSON) / current_price / position_vol / base_volume / action_payload(JSON) / order_no / reject_reason / created_at

### REQ-STRAT-004: regime 匹配规则

5 条规则**顺序生效**：
1. `enabled=False` 的 regime 跳过
2. `required_flags` 全部命中 `active_flags`（AND 语义）
3. `exclude_flags` 与 `active_flags` 无交集（NOT 语义）
4. 按 `priority DESC` 排序
5. 同 `priority` 按 `id ASC` 兜底

#### Scenario: 优先级高的先匹配

- **GIVEN** regime A priority=10 required=[ma_bullish]
- **AND** regime B priority=20 required=[ma_bullish]
- **WHEN** active_flags={ma_bullish: true}
- **THEN** MUST 选 B（priority 高）

#### Scenario: required 缺一不匹配

- **GIVEN** regime required=[ma_bullish, vol_breakout]
- **WHEN** active_flags={ma_bullish: true}
- **THEN** MUST 返 null

#### Scenario: exclude 命中不匹配

- **GIVEN** regime required=[ma_bullish] exclude=[rsi_overbought]
- **WHEN** active_flags={ma_bullish: true, rsi_overbought: true}
- **THEN** MUST 返 null

### REQ-STRAT-005: regime 冷却（防抖）

- 同 regime 切换间隔 ≥ 300s 才允许切换
- 5 分支决策：首次 / 无候选 / 同 regime / 冷却内 / 冷却外

#### Scenario: 同 regime 不算切换

- **GIVEN** last_switch_ts=T, current=A
- **WHEN** candidate=A
- **THEN** MUST 不更新 last_switch_ts

#### Scenario: 冷却内不切换

- **GIVEN** last_switch_ts=T-100, current=A, candidate=B
- **WHEN** cooldown=300
- **THEN** MUST 保持 A（不切 B）

### REQ-STRAT-006: grid 决策 — 底仓保护 + 整手

- 买单：`current_price <= trigger_price` 触发，`max_fires` 未耗尽
- 卖单：`current_price >= trigger_price` 触发，**`max_fires` 未耗尽**
  - **底仓保护**：`sell_volume = min(grid.volume, position_vol - effective_base_volume)`，钳制到 ≥ 0
  - **`effective_base_volume`**：regime.base_volume ?? strategy.base_volume
  - **整手取整**：`sell_volume = (sell_volume // 100) * 100`（LOT_SIZE=100）
  - 钳制后 `sell_volume = 0` → 拒绝（reject_reason=`floor_protected`）

#### Scenario: 底仓保护触发

- **GIVEN** position_vol=500, base_volume=300, grid.volume=300
- **THEN** sell_volume = min(300, 500-300) = 200
- **AND** 整手后 = 200

#### Scenario: clear_position 跳过底仓保护

- **GIVEN** regime.clear_position=true, position_vol=500, base_volume=300, grid.volume=300
- **THEN** sell_volume = 300（不钳制）

#### Scenario: 触发次数耗尽

- **GIVEN** grid.max_fires=2, fired_count=2
- **THEN** MUST 返 null

### REQ-STRAT-007: engine 评估入口（per-stock tick 驱动）

- `StrategyEngine` 维护：TickBuffer (deque maxlen=100) + last_regime + last_switch_ts + IndicatorParams + prev_close
- `evaluate_tick(tick, position_vol, base_volume, prev_close=None, now_ts=None, trd_date=None)` 8 步流水线：
  1. append tick → buffer
  2. compute indicators → compute flags
  3. match_regime
  4. apply_cooldown
  5. evaluate_grids (sell first, clear_position inserted first)
  6. 对每个 GridAction：写 audit + INSERT Order + ord_stk RPC + UPDATE status + increment fired_count
  7. broadcast strategy_update WS payload
  8. return EvaluateResult

#### Scenario: 无匹配 regime 不下单

- **GIVEN** buffer < 100 tick
- **WHEN** evaluate_tick
- **THEN** MUST 返 EvaluateResult(actions=[], matched_regime_id=null)

#### Scenario: 买单触发下单

- **GIVEN** grid direction=buy trigger_price=10.0
- **WHEN** current_price=9.5
- **THEN** MUST INSERT Order + ord_stk + audit

### REQ-STRAT-008: quote_consumer — 后端首次 WS 接入

- 单连接接 hqserver `ws://{HQ_WS_URL}:8765`（默认 `ws://127.0.0.1:8765`）
- hqserver **不支持** subscribe/unsubscribe（无条件广播），故 QuoteConsumer 全收 + 本地按 `stock_code` 过滤 fan-out
- 状态：`_engines: Dict[str, StrategyEngine]` + `_latest_price: Dict[str, float]` + `_stop: asyncio.Event`
- 启动时从 DB 读 `status='active'` 的 strategies，为每个 `stock_code` 建 engine
- `_load_prev_close(stock_code)` 从 `QuoteSnapshot` 表读最近一日的 `prev_close`，注入 engine
- `_subscribe_stock(stock_code)` / `_unsubscribe_stock(stock_code)` 仅本地字典管理（**不**发 WS 命令）

#### Scenario: 重连指数退避

- **WHEN** connect 失败
- **THEN** delay 序列 MUST 是 1s → 2s → 4s → 8s → 16s → 30s (cap)

#### Scenario: 60s 无 tick 警告

- **GIVEN** 连接活跃
- **WHEN** 60s 内无 tick
- **THEN** MUST log warning（**不**主动重连）

#### Scenario: 优雅停机

- **WHEN** stop()
- **THEN** _stop.set() → connect_loop 退出 + consume_loop 退出 + ws.close()

### REQ-STRAT-009: REST API（8 端点）

- `GET /api/strategy` — list（query: `status`, `type`）
- `POST /api/strategy` — create
- `GET /api/strategy/{id}` — detail
- `PUT /api/strategy/{id}` — update
- `DELETE /api/strategy/{id}` — delete（级联）
- `POST /api/strategy/{id}/control` — body: `{action: pause|resume|stop|clear_now}`
- `GET /api/strategy/{id}/audit?trd_date=YYYYMMDD` — list
- `GET /api/strategy/flags` — 注册表（不受灰度门控）
- 鉴权：除 `flags` 外全部需 `trader` 或 `admin`；trader 仅可操作自己的 strategy；admin 可操作全部
- 灰度门：`STRATEGY_ENGINE_ENABLED=false` → 除 `flags` 外全部返 503

#### Scenario: 灰度门关闭

- **GIVEN** STRATEGY_ENGINE_ENABLED=false
- **WHEN** GET /api/strategy
- **THEN** MUST 返 503

#### Scenario: flags 不受灰度门控

- **GIVEN** STRATEGY_ENGINE_ENABLED=false
- **WHEN** GET /api/strategy/flags
- **THEN** MUST 返 200 + 注册表

### REQ-STRAT-010: control action 语义

- `pause` — status: active → paused（停止 quote_consumer fan-out；保留 buffer / last_regime）
- `resume` — status: paused → active（重新订阅；last_switch_ts 不重置，regime 继续冷却）
- `stop` — status: * → stopped（永久停止；quote_consumer 不再加载）
- `clear_now` — 立刻把所有 position 卖光（生成 GridAction 走卖单，不受底仓保护），写 audit `trigger_type='clear_now'`

#### Scenario: clear_now 跳过底仓保护

- **GIVEN** position_vol=500, base_volume=300
- **WHEN** control action=clear_now
- **THEN** MUST 生成 sell 500 委托（含底仓），audit 写 trigger_type='clear_now'

### REQ-STRAT-011: WS payload `strategy_update` 频道

- 频道名常量 `STRATEGY_WS_CHANNEL = "strategy_update"`
- payload schema：
  ```json
  {
    "type": "strategy_update",
    "channel": "strategy_update",
    "ts": "ISO8601",
    "data": {
      "strategy_id": 5,
      "event": "regime_changed | grid_triggered | regime_cooldown",
      "regime_id": 11,
      "flags_active": ["ma_bullish", "vol_breakout"],
      "current_price": 10.5,
      "position_vol": 1000,
      "base_volume": 300,
      "action": { "direction": "buy", "volume": 200, "trigger_price": 10.0, "grid_id": 33 },
      "order_no": "ORD-001",
      "reject_reason": null,
      "trd_date": "20260706"
    }
  }
  ```
- 前端 ws_dispatch 收到 → 包装为 AuditRecord 推入 store.appendAudit
- 缺 `strategy_id` 静默丢弃

#### Scenario: strategy_update 缺 strategy_id 静默丢弃

- **WHEN** payload.data.strategy_id 缺失
- **THEN** MUST console.warn + 不写入 audit cache

### REQ-STRAT-012: Order.user_def 关联

- strategy 触发的下单，`Order.user_def = str(strategy.id)`（int → str）
- 索引 `ix_orders_user_def` on `user_def`（支撑 T0 端点 JOIN 过滤）
- `remark` 字段透传 `order_no`（与现有 REQ-TRADE-002 一致）

#### Scenario: strategy 委托 user_def=str(id)

- **GIVEN** strategy.id=5
- **WHEN** grid 触发下单
- **THEN** Order.user_def MUST = "5"

### REQ-STRAT-013: T0 端点 JOIN 迁移

- `server/api/t0_stats.py::t0_stats`：`Order.user_def == "T0"` 改为 `Order.user_def.in_(resolve_t0_user_defs(db, "T0"))`
- `resolve_t0_user_defs(db, "T0")` 返 Set[str]，含字面量 `"T0"` + 所有 `type='t0'` strategy.id 的字符串化
- 同样适用于 `t0_history` / `t0_exposure` / `t0_aggregate`
- 兼容：旧调用（无 db 参数）继续工作（fallback 到字面量集合）

#### Scenario: T0 端点含 t0 strategy 单子

- **GIVEN** strategy id=7, type=t0
- **WHEN** GET /api/t0/stats?t0_only=true
- **THEN** MUST 包含 user_def in {"T0", "7"} 的委托

---

## Script-Strategy 模块（v90 change, 2026-08-01）

> **背景**：REQ-STRAT-001~013 覆盖**网格策略引擎**（change strategy_trade，**2026-08-10 已删除**，见上文删除横幅）。v90 起新增独立的**脚本策略模块**（change script-strategy），允许用户在前端写 Python 脚本 + 回测 + 实盘。本节补登，也是当前 spec 的**主体**。
>
> **v120（2026-08-09 strategy-exec-service）**：脚本策略的**运行引擎**已迁到独立服务 `strategy_exec/`（Backtrader 重构，见 [`strategy-exec/spec.md`](../strategy-exec/spec.md)）。REQ-STRAT-014/015/017（数据模型 / REST API / 前端）仍在 EvTrade 不变；**REQ-STRAT-016 引擎运行时已迁移**，本节仅保留 EvTrade 侧仍相关的契约。
>
> **v122（2026-08-10 strategy-params-sweep-best-live）**：REQ-STRAT-016 扩展 2 端点（`POST /tasks/{id}/run-sweep` 转发 + `GET /tasks` 加 3 query params）+ TaskOut 加 4 字段。Sweep / best_params live 接入详见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-008 / REQ-SE-009。

### REQ-STRAT-014: 脚本策略数据模型（2 张表 + strategy_task 扩展）

- **`strategy_script`**（v90, 2026-08-04 起复合 PK `(user_id, id)`）
  - `id: varchar(64)` — 用户自命名（通常 = name），不再是自增 INT
  - `user_id: int` — 所属用户
  - `name: varchar(64)` — 脚本名（用户级唯一）
  - `code: longtext` — Python 源码（回调 `on_init` / `on_bar` / `on_tick` / `on_finish`，可用 `ctx.lib.MA / doorder`）
  - `params_schema: json` — 参数定义（key/type/default/min/max/step/values）
  - `description: varchar(255)`
  - `status: varchar(16)` — draft / active / archived
  - `is_public: tinyint` — 0=私有 / 1=公开（共享脚本市场）
  - `created_at / updated_at`
- **`strategy_script_audit`**（v90, 15 字段, bigint 自增 PK）
  - 关键字段：`task_id` / `stime`(YYYYMMDDHHMMSS) / `trd_date` / `phase`(bar/tick/on_init/on_finish) / `trigger_type`(BUY/SELL/SIGNAL/STOP/TP/INFO) / `stock_code` / `price` / `volume` / `indicators`(json) / `state`(json) / `msg` / `order_no` / `payload`(json) / `created_at`
- **`strategy_task` 扩展**（v90 多次 migration）
  - 新增字段：`script_id` (varchar 128) / `params` (json) / `backtest_result` (json) / `best_params` (json) / `backtest_start_date` / `backtest_end_date` / `period` / `pnl` (float) / `positions` (json) / `trades_count` / `started_at` / `finished_at` / `error_msg` (varchar 500) / `live_signals` (json, 限 500 条) / `fields` (历史行情字段白名单) / `progress` (json, 实时进度)
  - `mode` 字段：创建时不填，运行时（`/tasks/{id}/run`）再写

#### Scenario: 用户共享脚本（is_public=1）

- **GIVEN** user A 创建脚本 id='my_ma_cross', is_public=1
- **WHEN** user B 调用 GET /api/script-strategy/scripts
- **THEN** MUST 看到 user A 的脚本（user_id = me OR is_public = 1）
- **AND** 编辑/删除仅 user A 可见（user_id == me）

#### Scenario: 复合 PK ups

- **GIVEN** (user_id=1, id='cross_5_20') 已存在
- **WHEN** 同 user 创建 id='cross_5_20'
- **THEN** MUST 拒绝（unique violation）

### REQ-STRAT-015: script-strategy REST API（14 端点）

所有端点位于 `server/api/script_strategy/endpoints.py`，路由前缀 `/api/script-strategy`，依赖 `get_current_user`（部分需要 trader + admin）。

**scripts 子资源**（7 端点）：
- `GET    /scripts` — 列表（含分页 `page`/`page_size`，只返回 `user_id=me OR is_public=1`）
- `GET    /scripts/by-name/{name}` — 按 name 查
- `GET    /scripts/{script_id}` — 详情
- `POST   /scripts` — 创建（user_id 自动 = current_user.id）
- `PUT    /scripts/{script_id}` — 更新（仅 user_id=me）
- `DELETE /scripts/{script_id}` — 删除（仅 user_id=me）

**tasks 子资源**（7 端点）：
- `GET    /tasks` — 列表
- `GET    /tasks/{task_id}` — 详情（含 progress / live_signals）
- `POST   /tasks` — 创建（status='created', mode 留空）
- `POST   /tasks/{task_id}/run` — 启动（写 mode='backtest' 或 'live'，异步）
- `POST   /tasks/{task_id}/stop` — 停止（live 模式生效）
- `DELETE /tasks/{task_id}` — 删除
- `GET    /tasks/{task_id}/logs` — 运行日志（回测完整 / 实盘最近 N 条）
- `GET    /tasks/{task_id}/signals` — 信号流

**templates**（1 端点）：
- `GET    /templates/default` — 默认脚本模板（前端编辑器初始化用）

#### Scenario: 创建脚本 task 并启动回测

- **WHEN** POST /tasks {script_id, params, backtest_start_date, backtest_end_date}
- **THEN** 创建 row (status='created')
- **AND** 立即返回 task_id（异步不等待回测完成）
- **WHEN** 客户端 POST /tasks/{id}/run
- **THEN** 写 mode='backtest', status='running', started_at=now
- **AND** 回测引擎在 strategy_exec 跑（见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-003）
- **AND** progress 字段实时更新（通过 `task_progress_update` ws 推送）
- **WHEN** 回测完成
- **THEN** 写 backtest_result / best_params / pnl / trades_count / finished_at / status='completed'

### REQ-STRAT-016: 回测 / 实盘引擎运行时（v120 已迁移 strategy_exec, v122 扩 sweep + best）

> **v120 迁移（2026-08-09 strategy-exec-service）**：回测/实盘引擎已迁到独立服务 `strategy_exec/`（Backtrader 重构，基于 `bt.Cerebro`）。原 `server/strategy/runtime/` 目录已删除。引擎实现见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-003（引擎）/ REQ-SE-004（RabbitMQ 信号推送）/ REQ-SE-005（用户脚本接口）。本节仅保留 **EvTrade 侧仍相关**的契约：

- 用户脚本接口 **BREAKING**：v90 `on_bar/on_tick/ctx.lib.doorder` 废弃，改为 Backtrader `ProjectStrategy.next()` + `self.buy_signal()/self.sell_signal()`（见 strategy-exec REQ-SE-005；迁移指南 `docs/strategy-migration-v90-to-bt.md`）
- `live_signals` 环形缓冲（限 500 条，每 5s flush 到 DB）：由 strategy_exec `LiveRunner` 实现（`append_live_signals`）
- 风险档位集成（`RiskChecker`，**仍 EvTrade 侧**）：单笔最大 / 当日笔数 / 单股仓位上限 / 最大回撤 — 触发即拒单
- signal 消费 + 下单：EvTrade `server/services/strategy/signal_consumer.py` 订阅 signal → 调 `/api/orders/place`

#### v122 扩展（2026-08-10 strategy-params-sweep-best-live）

EvTrade 转发层加 2 端点，TaskOut 加 4 字段。完整 sweep 引擎语义 + best_params live 接入见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-008 / REQ-SE-009。

**新增端点 1** — `POST /api/strategy/tasks/{id}/run-sweep`（转发到 strategy_exec）：

Request：

```jsonc
{
    "param_grid": { "fast": [3,5,7,10], "slow": [15,20,30,60] },
    "metric": "sharpe",
    "select_top_n": 1,
    "concurrency": 2
}
```

Response（202）：

```jsonc
{
    "sweep_id": "abc123...",
    "total_runs": 16,
    "summary_task_id": 42
}
```

行为：

- 鉴权同 `run-task`（需登录，普通用户只能 sweep 自己的，admin 任意）
- `task_id`（path）必须是该用户的未开始 task（status='pending'）；sweep 创建子 task 全部继承此父 task 的 script_id / stock_code
- EvTrade 端不存 sweep 状态（strategy_exec 单独写 strategy_task 表）
- 预创建 N+1 个 strategy_task 行（sweep_id 共享），再转发 strategy_exec

**新增端点 2** — `GET /api/strategy/tasks` 加 query params：

- `script_id`: 限定脚本
- `status='finished'`: 仅已完成
- `has_best_params=1`: 仅 best_params 非空（含单 run 退化 + sweep summary）
- `limit=50`: 默认 50，最大 200（endpoint 层强制）

**TaskOut 扩字段**（共 4）：

- `sweep_id: Optional[str]`
- `sweep_metric: Optional[str]`
- `sweep_total: Optional[int]`
- `backtest_metric_value: Optional[float]` — 已持久化到 `strategy_task.backtest_metric_value` 列（strategy_exec 完成时一并写, 语义 sharpe→total_return→pnl/initial_cash）；列表查询用列免拖回大 blob, 规避 MySQL 1038。老行/未回填时读端回退解析 `backtest_result`。sweep summary 语义见 sweep 引擎（v123 不再建 summary task）。

#### Scenario: 回测进度推送

- **GIVEN** 回测中, 当前 bar_idx=500, total_bars=10000
- **WHEN** strategy_exec 回测主循环每 N bar 写一次 progress（`update_task_progress`）
- **THEN** `strategy_task.progress` 更新为 `{phase: 'bar', current: 500, total: 10000, bar_idx: 500, total_bars: 10000, elapsed_ms: ...}`
- **AND** EvTrade ws_manager 读 DB 变化推 `task_progress_update` channel（前端 ScriptTask.vue 详情实时刷新）

#### Scenario: 实盘 live_signals 限 500

- **WHEN** strategy_exec live_signals 累计达 500 条
- **THEN** 第 501 条起**覆盖**最早（环形缓冲，`append_live_signals`）
- **AND** 每 5s flush 到 DB（不是逐条写 — 避免高频 IO）

#### Scenario: sweep 16 组合全成功 (v122)

- **WHEN** POST /tasks/{id}/run-sweep with `param_grid = {fast: [3,5,7,10], slow: [15,20,30,60]}`
- **THEN** EvTrade 预创建 16 个 task + 1 个 summary task（共享 sweep_id）
- **AND** 转发 strategy_exec → run_sweep 异步跑 16 组合
- **AND** summary task 最终 status='finished', best_params=排序 top1 组合
- **AND** 用户 GET /tasks?has_best_params=1&script_id=mas_v1 看到 summary task，backtest_metric_value=top1 sharpe

#### Scenario: sweep grid 超硬上限 (v122)

- **WHEN** count_grid_size(param_grid) > 512
- **THEN** EvTrade 端返 400, `{"code": "GRID_TOO_LARGE", "msg": "组合数 N 超过硬上限 512, 请缩小网格"}`
- **AND** 不创建任何 strategy_task 行

#### Scenario: live 启动用 sweep best_params (v122)

- **WHEN** 用户在 ScriptTask 启实盘，选 task #42（sweep summary best: fast=7, slow=30）
- **THEN** POST /tasks with `mode='live', params={fast:7, slow:30, qty:100, rsi_period:14}`
- **AND** EvTrade 转发 strategy_exec → LiveRunner 用 cls.p.fast=7, cls.p.slow=30 算信号

### REQ-STRAT-017: 前端 2 个 view + 14 端点客户端

- **`client/src/views/ScriptDev.vue`** — 策略开发页
  - 左 CodeMirror/Monaco 代码编辑器（70% 宽）+ 右参数 schema 列表（30%）
  - 顶部：脚本名、描述、状态徽章、保存按钮、测试回测按钮
  - 底部：保存后显示"去回测"按钮 → 跳 `ScriptTask.vue?script_id=...`
- **`client/src/views/ScriptTask.vue`** — 策略运行页（路由 label "策略运行"，v97 重命名）
  - 任务列表 + 详情（progress / live_signals / logs / signals）
  - 订阅 ws `task_progress_update` channel 实时刷新 progress
- 客户端封装：`client/src/api/script_strategy.js`（与 `client/src/api/strategy.js` 分离）

#### Scenario: ScriptDev → ScriptTask 跳转

- **WHEN** 用户在 ScriptDev.vue 保存脚本（POST /scripts）
- **THEN** 返回 script_id
- **WHEN** 用户点"去回测"
- **THEN** `router.push({path: '/script-task', query: {script_id}})`
- **AND** ScriptTask.vue onMounted 自动用 script_id 预填创建 task 表单

### REQ-STRAT-018: 批次重测（v124 change, 2026-08-11）

批次列表支持**重测**：按原批次配置（params / 标的 / 区间 / 周期 / metric）重建一个**新批次**（新
`batch_no`, 全部 task status='queued'）并重新执行；原批次全部 task 置 `status='abandoned'`（废弃,
不再计入 finished/failed/best）。

**端点**：

- `POST /strategies/{strategy_id}/batches/{batch_no}/retest` → 202 `{batch_no, total_runs, mode, metric, over_soft_limit}`
  - 校验：批次存在 / 归属策略有权限 / `mode='backtest'`（live 不可重测 → 400 `NOT_RETESTABLE`）
  - **运行中批次拒绝**：仍有 `queued`/`running` task → 409 `BATCH_RUNNING`（strategy_exec 正写这些行,
    废弃会被覆盖）
  - 原批次 task 全部 → `abandoned`（批量 `UPDATE strategy_task SET status='abandoned' WHERE strategy_id+batch_no`）
  - 新批次转发 strategy_exec：sweep → `/internal/run-sweep-task`（`param_ranges` 由 task params 去重重建,
    与 strategy_exec `iter_param_ranges` 精确同网格）; single → `/internal/run-task`
  - 废弃的 task 行保留（可追溯历史）, 不删除

**metric 持久化（v124 起）**：

- `strategy_task` 增 `metric VARCHAR(16)` 列, 批次创建时落库（`create_backtest_batch` 传 metric）
- 老批次回填 `'sharpe'`（无历史记录, 用默认排序指标）
- 重测读取原批次 task 的 metric 忠实还原; 若未持久化（老批次）回退 `'sharpe'`

**批次列表扩展**（`BatchOut`）：

- `metric: str` — 批次排序指标
- `abandoned_count: int` — 废弃 task 数
- `abandoned: bool` — 批次已全部废弃（被重测替代）
- best 聚合只看**非废弃** finished task

#### Scenario: 重测单次回测批次

- **GIVEN** batch #B（single, 1 个 finished task, params={fast:3, slow:2}）
- **WHEN** POST /strategies/{id}/batches/{B}/retest
- **THEN** 原 batch #B 的 task status → 'abandoned'（批次列表显示"已废弃"）
- **AND** 生成新 batch #B'（1 个 queued task, 同 params）, 转发 strategy_exec 重新跑
- **AND** 响应 `{batch_no: B', total_runs: 1, mode: 'single'}`

#### Scenario: 重测参数扫描批次（忠实还原 metric）

- **GIVEN** batch #S（sweep, 6 个 finished task, metric='total_return', param_ranges 展开 6 组合）
- **WHEN** POST /strategies/{id}/batches/{S}/retest
- **THEN** 原 batch #S 全部 task → 'abandoned'
- **AND** 新 batch #S' 建 6 个 queued task, 读取原 task 的 metric='total_return'
- **AND** param_ranges 由 6 个 task params 去重重建（`{fast: choice[1,2,3], slow: choice[5,10]}`）
- **AND** 转发 strategy_exec 用 metric='total_return' 选 top1

#### Scenario: 运行中批次禁止重测

- **GIVEN** batch #R 有 1 个 running task
- **WHEN** POST /strategies/{id}/batches/{R}/retest
- **THEN** 返回 409 `{"code": "BATCH_RUNNING"}`
- **AND** 不生成新批次, 不废弃原任务

### REQ-STRAT-019: 策略可见性与权限矩阵 (v125 change, 2026-08-11)

策略模块改为**纯回测**:策略级显式 `is_public` + 绑定标的 `stock_code`,他人公开策略只读精简可见、不可回测。实盘/黑盒跟随移出本模块(Part 2 策略下单另行设计)。

**数据模型**(`strategy` 表 +2 列,迁移 `2026-08-11-add-strategy-visibility.py`):

- `is_public: tinyint NOT NULL DEFAULT 0` — 0=私有(默认) 1=公开(列表可见,供策略下单选择);**存量策略默认私有**(迁移默认 0)
- `stock_code: varchar(16) NULL` — 策略绑定标的(新建必填,只针对此标的回测;存量 NULL 回退请求标的)
- `create_strategy` 必填 `stock_code`;标的创建后不可改(update 不含该字段)

**权限矩阵**:

| 操作 | 本人(owner) | 他人·公开策略 | 他人·私有策略 |
|---|---|---|---|
| 列表可见 | ✓(完整) | ✓(精简卡片) | ✗ 404 |
| 查看详情 | ✓(含脚本/参数) | ✓ 精简(不含代码/best_params) | ✗ 404 |
| 修改/删除/公开开关 | ✓ | ✗ | ✗ |
| 回测/批次/重测 | ✓ | ✗ 403 BACKTEST_FORBIDDEN | ✗ 404 STRATEGY_NOT_FOUND |

- 隐私原则:他人**私有**策略一律 `404 STRATEGY_NOT_FOUND`(不泄漏存在性);他人**公开**策略的受限操作(回测)返回 `403`(用户已在列表看到它)。
- 错误码:`403 BACKTEST_FORBIDDEN` / `404 STRATEGY_NOT_FOUND` / `400 STOCK_MISMATCH` / `400 MISSING_STOCK`。

**端点变更**:

- 删除 `POST /strategies/{strategy_id}/live`(策略模块纯回测;实盘能力 Part 2 重建)
- `POST /strategies/{strategy_id}` 请求加必填 `stock_code`
- `PUT /strategies/{strategy_id}` 可改 `is_public`
- `GET /strategies` / `GET /strategies/{id}`:他人公开返回精简视图(`is_public` + `stock_code`,无 `script`/`best_params`)
- `BacktestRequest.stock_code` 改 Optional(标的由策略绑定决定;提供且不匹配 → `400 STOCK_MISMATCH`)

**前端**:

- `ScriptTask.vue`:新建策略必选标的;列表区分「我的 / 公开」;他人公开策略**只读精简卡片**(无回测/批次/编辑入口);公开/私有开关仅 owner;移除「实盘」按钮 + live 徽章
- `ScriptDev.vue`:他人公开脚本表单只读(禁用编辑/删除/保存)

#### Scenario: 作者发布公开策略

- **GIVEN** 用户 A 创建策略(必填标的 600519.SH),设 `is_public=true`
- **WHEN** 用户 B 调 GET /strategies
- **THEN** 看到 A 的策略精简卡片(名称/标的/owner/is_public),不含脚本源码与 best_params
- **AND** B 调 GET /strategies/{id} → 精简视图;调回测/批次 → `403 {"code": "BACKTEST_FORBIDDEN"}`

#### Scenario: 非 owner 回测被拒

- **GIVEN** 用户 A 的私有策略
- **WHEN** 用户 B 调 GET /strategies 或回测
- **THEN** 一律 `404 {"code": "STRATEGY_NOT_FOUND"}`,不泄漏策略存在性

#### Scenario: 策略绑定标的 + 回测标的失配

- **GIVEN** 策略绑定 600519.SH
- **WHEN** 回测请求带 `stock_code=000001.SZ`
- **THEN** 返回 `400 {"code": "STOCK_MISMATCH"}`
- **AND** 回测不带 stock_code → 固定用策略绑定标的 600519.SH

### REQ-STRAT-020: 策略母单与实盘下单 (v126 change, 2026-08-11)

承接 v125 Part 2（§8 拆出）。策略模块 v125 切纯回测后，本 change 重建**实盘下单**入口：用户为已回测出 `best_params` 的策略创建**母单 `strategy_order`**，母单启动后复用 `strategy_exec` LiveRunner 跑实盘，触发的真实子单归因到母单。

**数据模型**（迁移 `2026-08-11-add-strategy-order.py`）:

- 新表 `strategy_order`（母单）：`id` / `task_id`（UNIQUE, `order_no_seq` 的 `strategy_order` 生成器）/ `user_id` / `strategy_id` / `stock_code`（冗余自 `strategy.stock_code`）/ `status`（`stopped` 默认 / `running` / `closed`）/ `active_task_id`（当前 live `strategy_task.id`）/ `run_count` / `last_started_at` / `last_stopped_at` / `closed_at` / 时间戳。索引 `UNIQUE(task_id)` + `KEY(user_id)` + `KEY(strategy_id)`。
- `orders.strategy_type` 列 COMMENT 更新（0=普通单 / 1=快速做T / **2=策略下单**），列类型 TINYINT 不变。`server/api/orders/schemas.py` 的 `strategy_type: Literal[0, 1]` → `Literal[0, 1, 2]`；`OrderOut.strategy_type` 注释同步。
- `strategy_task` 不改结构（v125 仅删 API 层 `/live`；表字段本就支持 `mode='live'`）。母单**不存 params**：每次启动读当前 `strategy.best_params` 快照到 `strategy_task.params`。

**信号链路（方案 B：payload 携带 `parent_task_id` + `strategy_name`）**:

- `strategy_exec`：`Signal` 加 `parent_task_id: Optional[int]` + `strategy_name: str`（`asdict` 自动序列化）；`_set_task_meta` / `LiveRunner` / `start_live_runner` / `RunTaskRequest` 全部加 2 个带默认值的可选参数，回测路径签名兼容。
- EvTrade `signal_consumer` 改为：
  - `task_id = payload.parent_task_id`（母单 `task_id` → `orders.task_id`）
  - `user_def = payload.strategy_name`（策略名）
  - `strategy_type = 2`
  - 回测信号（`mode == 'backtest'` / `parent_task_id is None`）仍跳过不下单；INFO 仍跳过。

**母单 REST（`/api/script-strategy/strategy-orders`，仅 owner / admin）**:

| 端点 | 行为 |
|---|---|
| `POST /strategy-orders` body `{strategy_id}` | 校验策略存在 + owner（他人私有→`404 STRATEGY_NOT_FOUND`，不泄漏）+ `best_params` 非空（否则 `400 NO_BEST_PARAMS`）→ `next_seq("strategy_order")` 生成 `task_id` → 建母单（`status=stopped`）→ 201 |
| `GET /strategy-orders` | 我的母单列表（admin 全部），JOIN 策略名 + 子单数（`orders.task_id=母单.task_id` COUNT） |
| `GET /strategy-orders/{id}` | 详情（策略名 / 标的 / 状态 / `run_count` / 子单数） |
| `POST /strategy-orders/{id}/start` | 校验非 `closed`（否则 `409 INVALID_STATE`）→ 读 `strategy.best_params`（空→`400 NO_BEST_PARAMS`）→ `create_task(mode='live', ...)` → 转发 `/internal/run-task` 带 `parent_task_id`+`strategy_name` → `status=running`、记 `active_task_id`、`run_count+1`、`last_started_at` |
| `POST /strategy-orders/{id}/stop` | 校验 `running` 且 `active_task_id`（否则 `409 INVALID_STATE`）→ 转发 `/internal/stop-task(active_task_id)` → `status=stopped`、`active_task_id=NULL`、`last_stopped_at` |
| `POST /strategy-orders/{id}/close` | 校验非 `running`（否则 `409`）→ `status=closed`、`closed_at`（**保审计不硬删**） |

错误码：`404 STRATEGY_NOT_FOUND`（含他人私有存在性隐藏）/ `400 NO_BEST_PARAMS` / `409 INVALID_STATE` / `403 FORBIDDEN`。

**权限**：仅 owner（或 admin）可建/启/停/关母单；他**人公开**策略的 `best_params` 不外露（REQ-STRAT-019 精简视图），**不可建母单**（与 v125 R5 一致）。

**前端**：

- 新页 `client/src/views/StrategyOrder.vue`，路由 `/strategy-order`，桌面 NavBar 加「策略下单」入口（BottomNav 不加）。
- 4 面板：**策略下单**（下拉选自己策略，**仅 `best_params` 非空可选中**，空时置灰「需先回测出最佳参数」→ 显示标的 / 「已回测」标记 / 「创建母单」）/ **行情面板**（复用 `QuotePanel.vue`，跟随选中母单/策略的 `stock_code`）/ **策略母单**（`GET /strategy-orders` 列表，含 task_id / 策略名 / 标的 / 状态徽章 / `run_count` / 子单数 / [启动|停止] / 关闭，选中行联动子单面板）/ **委托子单**（`holdings.orders.filter(o => o.strategy_type===2 && Number(o.task_id)===选中母单.task_id)`，T0Trade 同款本地缓存过滤，实时）。
- **T0 视图防御过滤**：`T0Trade.vue` 委托过滤加 `strategy_type !== 2` 条件，与策略单按 `strategy_type` 互斥，防 `task_id` 撞号串视图。
- 状态徽章：`stopped`=默认 / `running`=进行中 / `closed`=已关闭；`running` 禁用「关闭」，`closed` 禁用「启动」。

#### Scenario: 母单可重复启停 + 子单累积归因

- **GIVEN** 用户 A 的策略 `s1`（`best_params` 非空，标的 600519.SH）
- **WHEN** A 调 `POST /strategy-orders {strategy_id: s1}` → 启动 → 停止 → 启动（第二次）
- **THEN** 母单 `status` 走 `stopped → running → stopped → running`；`run_count=2`；`active_task_id` 在两次启动间变化（指向各自的 `strategy_task.id`）；两次运行的子单全部 `orders.task_id = 母单.task_id` + `strategy_type=2` + `user_def=策略名`，可按母单统一过滤

#### Scenario: 无 best_params 拒绝建母单

- **GIVEN** 用户 A 的策略 `s2`（`best_params` 为 NULL）
- **WHEN** A 调 `POST /strategy-orders {strategy_id: s2}`
- **THEN** 返回 `400 {"code": "NO_BEST_PARAMS"}`，未建母单、未占 `task_id`

#### Scenario: 他人公开策略不可建母单

- **GIVEN** 用户 A 的策略 `s3`（`is_public=true`），用户 B 看到精简视图
- **WHEN** B 调 `POST /strategy-orders {strategy_id: s3}`
- **THEN** 返回 `403 {"code": "FORBIDDEN"}`（B 已在列表看到 `s3`，存在性无需隐藏；best_params 仍不外露）

#### Scenario: 非法状态转移

- **GIVEN** 母单 `o1` 处于 `running`
- **WHEN** A 调 `POST /strategy-orders/o1/start`（再启）
- **THEN** 返回 `409 {"code": "INVALID_STATE"}`
- **AND** A 调 `POST /strategy-orders/o1/close` → 同 `409`
- **AND** `o1` 处于 `closed` 时调 `start` → `409`

#### Scenario: T0 视图与策略单互斥

- **GIVEN** T0 委托 `o_t0`（`strategy_type=1`）+ 策略子单 `o_strat`（`strategy_type=2`），`task_id` 同值
- **WHEN** T0Trade.vue 渲染委托列表
- **THEN** `o_t0` 出现，`o_strat` 被 `strategy_type !== 2` 过滤排除
- **AND** StrategyOrder.vue 渲染子单面板：仅 `o_strat` 出现，`o_t0` 被 `strategy_type===2` 过滤排除

## Cross References

- 行情来源：`quotes/spec.md` REQ-QUOTE-001（hqserver 推送）
- 委托下发：`trading/spec.md` REQ-TRADE-002（place 流程 + user_def 关联） + `data-model/spec.md` §14 `orders.strategy_type` 列（0/1/**2** 扩展）
- 脚本策略脚本：脚本字段（`code`/`params_schema`/`is_public`）定义在 `data-model/spec.md`（`strategy_script` 表）
- 脚本策略审计：定义在 `data-model/spec.md`（`strategy_script_audit` 表）
- 引擎：`strategy-exec/spec.md` REQ-SE-003~005（Backtrader 引擎 / RabbitMQ 信号 / 用户脚本接口） + REQ-SE-008~009（LiveRunner / Signal payload）
- 策略数据：`data-model/spec.md` `strategy` 表 + `REQ-STRAT-019` `is_public` / `stock_code` / `best_params` 门禁
- WS 推送：`push/spec.md`（`task_progress_update` 频道，ScriptTask.vue 实时刷新）
- 前端：`frontend/spec.md`（ScriptDev.vue / ScriptTask.vue / StrategyOrder.vue / T0Trade.vue 防御过滤）

- 行情来源：`quotes/spec.md` REQ-QUOTE-001（hqserver 推送）
- 委托下发：`trading/spec.md` REQ-TRADE-002（place 流程 + user_def 关联）
- 脚本策略脚本：脚本字段（`code`/`params_schema`/`is_public`）定义在 `data-model/spec.md`（`strategy_script` 表）
- 脚本策略审计：定义在 `data-model/spec.md`（`strategy_script_audit` 表）
- 引擎：`strategy-exec/spec.md` REQ-SE-003~005（Backtrader 引擎 / RabbitMQ 信号 / 用户脚本接口）
- WS 推送：`push/spec.md`（`task_progress_update` 频道，ScriptTask.vue 实时刷新）
- 前端：`frontend/spec.md`（ScriptDev.vue / ScriptTask.vue）
- 配置：`configuration/spec.md` REQ-CFG-012（strategy_exec env）