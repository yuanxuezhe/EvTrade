# strategy — 网格策略交易引擎

## Purpose

策略引擎让 trader 给单只标的配置**多档参数集 (regime)**，每档绑定一组**量价标志 (flags)**，由后端实时订阅 hqserver 行情推送驱动，自动匹配当前应启用的参数集（含优先级），按该参数集的网格配置下单。核心约束：**卖单绝不允许突破底仓**（除非该 regime 设了 `clear_position=true`）。

数据本地 DB 优先（沿用 v4 架构）：策略配置 → DB；触发审计 → DB；下单走 `ord_stk` 与 trader 手动下单同路径，`user_def = str(strategy.id)`（裸 strategy_id 作 key）作为 Order → Strategy 的关联字段。

## Requirements

### REQ-STRAT-001: 数据模型

策略 / 参数集 / 网格 / 审计 4 张表结构与外键约束见 `data-model/spec.md` §2.4（本 change 新增）。

- `Strategy` —— 顶层策略，归属 user，绑定单标的；**含 `type VARCHAR(16)` 字段区分 `'general'` / `'t0'`**
- `StrategyRegime` —— 参数集，多对一策略，含 priority + required_flags + exclude_flags + base_volume override + clear_position 标志
- `StrategyGrid` —— 网格，多对一参数集，含 direction + step_offset + volume + max_fires + fired_count + priority
- `StrategyAudit` —— 触发审计日志，每次评估无论是否触发都写一行

**索引**：
- `Strategy` 加 `Index("ix_strategy_type", "type")` — 支撑 T0 端点 JOIN 过滤
- `Order` 加 `Index("ix_orders_user_def", "user_def")` — 支撑策略关联查询

#### Scenario: cascade delete 清理子表

- **WHEN** 删 Strategy(id=X)
- **THEN** StrategyRegime/StrategyGrid/StrategyAudit 中 strategy_id=X 的所有 row 一并删除（ON DELETE CASCADE）

#### Scenario: Strategy.type 取值校验

- **WHEN** 创建策略时 POST /api/strategy/ body.type ∉ {'general', 't0'}
- **THEN** 返 422 `type must be one of ['general', 't0']`
- **AND** 默认值 `type='general'`（创建 body 不传 type 时）

#### Scenario: 同 (user, stock_code) 同 type 唯一 active

- **WHEN** 已有 Strategy(user=1, stock_code='600519.SH', type='t0', status='active')
- **AND** 新建 Strategy(user=1, stock_code='600519.SH', type='t0', status='active')
- **THEN** 返 409 `{code: STRATEGY_CONFLICT, msg: '同 user+stock_code+type 已存在 active 策略'}`
- **AND** 同一 user + stock_code + type='general' 可与 type='t0' 共存（不同 type 互不冲突）

### REQ-STRAT-002: 量价标志（v1 后端硬编码 8 种）

`server/services/strategy/flags.py` MUST 导出固定 8 种标志的注册表，每种含 code / name / category / description / compute 函数。前端通过 `GET /api/strategy/flags/definitions` 获取完整列表做下拉。

| code | name | category | 触发条件（基于 TickBuffer） |
|---|---|---|---|
| `ma_bullish` | 均线多头 | trend | MA5 > MA10 > MA20 |
| `ma_bearish` | 均线空头 | trend | MA5 < MA10 < MA20 |
| `rsi_overbought` | RSI超买 | oscillator | RSI(6) ≥ 70 |
| `rsi_oversold` | RSI超卖 | oscillator | RSI(6) ≤ 30 |
| `vol_breakout` | 量能突破 | volume | 当根 vol ≥ 2× MA_VOL(20) |
| `price_change_up` | 涨幅≥1% | momentum | (last - prev_close) / prev_close ≥ 0.01 |
| `price_change_down` | 跌幅≤-1% | momentum | (last - prev_close) / prev_close ≤ -0.01 |
| `macd_golden_cross` | MACD金叉 | trend | DIF > DEA 且 1 根前 DIF ≤ DEA |
| `macd_death_cross` | MACD死叉 | trend | DIF < DEA 且 1 根前 DIF ≥ DEA |

#### Scenario: 标志定义 API

- **WHEN** GET /api/strategy/flags/definitions（任意已登录用户）
- **THEN** 返 200 + `[{code, name, category, description}, ...]` 共 9 项（v1 列表）

#### Scenario: 标志检测输入 buffer 不足

- **WHEN** TickBuffer 内 tick 数 < 该指标所需 period（如 RSI 需要 6+ 根）
- **THEN** 对应标志 MUST NOT 出现在 active flags 集合，不抛错

### REQ-STRAT-003: 参数集（Regime）匹配

`server/services/strategy/regime.py::match_regime(regimes, active_flags) -> Optional[StrategyRegime]` MUST 按以下规则匹配当前应启用的参数集：

1. 仅考虑 `enabled=true` 的参数集
2. `required_flags` 必须是 `active_flags` 的子集（AND 逻辑）
3. `exclude_flags` 与 `active_flags` 交集 MUST 为空（NOT 逻辑）
4. 多个候选时取 `priority` 最高者；priority 并列取 `id` 最小者（创建顺序在前）
5. 无候选时返回 `None`（引擎暂停下单）

#### Scenario: 单参数集匹配

- **WHEN** Strategy 唯一 Regime R1，R1.required_flags = ["ma_bullish"]
- **AND** active_flags = {"ma_bullish", "rsi_overbought"}
- **THEN** match_regime 返 R1

#### Scenario: 多参数集按 priority 胜出

- **WHEN** R1.priority=10, required=["ma_bullish"]；R2.priority=20, required=["rsi_overbought"]
- **AND** active_flags = {"ma_bullish", "rsi_overbought"}
- **THEN** match_regime 返 R2（priority 更高）

#### Scenario: required_flags 缺一不可

- **WHEN** R1.required_flags = ["ma_bullish", "macd_golden_cross"]
- **AND** active_flags = {"ma_bullish"}（无 MACD 金叉）
- **THEN** match_regime 跳过 R1（必需标志未全到）

#### Scenario: exclude_flags 排除

- **WHEN** R1.required_flags = []（任意），exclude_flags = ["ma_bearish"]
- **AND** active_flags = {"ma_bearish", "rsi_overbought"}
- **THEN** match_regime 跳过 R1（被排除）

#### Scenario: cooldown 防止频繁切换

- **WHEN** R1 在 10:00:00 被激活
- **AND** 10:02:00 active_flags 又匹配到 R2
- **THEN** regime cooldown（默认 5min）生效，保持 R1 不切换到 R2，audit 记 `regime_cooldown`

### REQ-STRAT-004: 底仓保护（核心安全约束）

`server/services/strategy/grid.py::plan_sell(grid, position_vol, base_volume)` MUST 满足：

- `available_to_sell = max(0, position_vol - base_volume)`
- 若 `available_to_sell <= 0`：返 `None`（已到底仓，不卖）
- 否则 `sell_vol = min(grid.volume, available_to_sell)`
- `sell_vol` MUST 向下取整到 100 的倍数（整手）
- 若整手后 `sell_vol <= 0`：返 `None`（不触发碎片单）

**关键不变式**：所有非 `clear_position=true` 路径下，`position.vol ≥ strategy.base_volume` 恒成立。

#### Scenario: 持仓 500 / 底仓 100 / sell.volume=200

- **WHEN** plan_sell(grid, position_vol=500, base_volume=100)
- **THEN** 返回 200（min(200, 400) = 200，整手后 200）

#### Scenario: 持仓 100 / 底仓 100 / sell.volume=200（已到底仓）

- **WHEN** plan_sell(grid, position_vol=100, base_volume=100)
- **THEN** 返回 None（available_to_sell = 0，不触发卖单）

#### Scenario: 持仓 250 / 底仓 100 / sell.volume=200（整手取整后归零）

- **WHEN** plan_sell(grid, position_vol=250, base_volume=100)
- **THEN** 返回 None（available_to_sell=150 → 整手 100？实为 150 整手 = 100，仍触发 100 股）

#### Scenario: 持仓 199 / 底仓 100 / sell.volume=200（碎片整手归零）

- **WHEN** plan_sell(grid, position_vol=199, base_volume=100)
- **THEN** available_to_sell=99 → 整手 (99//100)*100 = 0 → 返 None

### REQ-STRAT-005: 清仓标志（唯一合法打破底仓路径）

`StrategyRegime.clear_position=true` MUST 触发 `plan_clear(position_vol) = position_vol`（全部卖出含底仓）。

#### Scenario: clear_position regime 激活

- **WHEN** 当前 regime.clear_position=true 且被 match_regime 命中
- **AND** position_vol = 500（底仓 100）
- **THEN** engine MUST 调用 plan_clear(500) → 下卖单 500 股，全部清空（含底仓）

#### Scenario: clear 后 regime 退出

- **WHEN** clear_position regime 触发清仓后，下一 tick active_flags 不再匹配该 regime
- **THEN** 引擎切换到其他 regime 或暂停（无匹配），后续评估不再触发 clear（直到重新匹配）

### REQ-STRAT-006: 评估触发 = tick 驱动 + 整批

每次 hqserver tick 到达活跃策略订阅的 stock_code 时，`StrategyEngine.evaluate_tick(tick, position_vol, base_volume)` MUST 按顺序执行：

1. 更新 TickBuffer（append tick + 滑动窗口）
2. 重算 active_flags（`flags.detect_flags(buffer)`）
3. 匹配 regime（`regime.match_regime(...)` + cooldown 检查）
4. 若 regime 切换：emit `strategy_update {type: 'regime_changed'}` + audit 写入 `trigger_type='regime_switch'`
5. 对当前 regime 所有 enabled grids：调用 `plan_buy / plan_sell / plan_clear`
6. 对每个 action 队列按 sell 优先 buy 在后排序
7. 串行调 `server.api.orders.ord_stk`（带 `user_def = str(strategy.id)`）
8. 每个 action（含拒触发）都写 audit

#### Scenario: 单 tick 触发 buy grid

- **WHEN** 当前 regime 含 buy grid: trigger_price=12.00, volume=100
- **AND** tick.last_price=11.95 ≤ trigger_price
- **THEN** engine MUST 下买单 100 股 @ latest，audit 记 `trigger_type='grid_buy'`，WS 广播 `strategy_update {type: 'grid_triggered'}`

#### Scenario: 单 tick 触发 sell grid（受底仓保护）

- **WHEN** 当前 regime 含 sell grid: volume=200
- **AND** tick.last_price=12.50 ≥ reference+step_offset
- **AND** position_vol=500, base_volume=400
- **THEN** available_to_sell=100 → 实际下卖单 100 股（不是 200），audit 记 `reject_reason=null`（plan_sell 返回 100，非 None）

#### Scenario: 单 tick 内 buy + sell 同时触发

- **WHEN** 当前 regime 含 buy grid 100 @ 11.95 + sell grid 200 @ 12.50
- **AND** tick.last_price 双向都不达（11.95 < 11.95 false、11.95 ≥ 12.50 false）
- **THEN** 无 action，audit 记 `trigger_type='no_action'`

#### Scenario: sell 优先于 buy（防底仓被穿）

- **WHEN** 单 tick 内同时触发 sell 100 + buy 200
- **THEN** engine MUST 先调 sell ord_stk（broker 同步返回 order_no）→ 再调 buy ord_stk（避免 buy 成功但 sell 排队中时底仓被临时突破）

### REQ-STRAT-007: quote_consumer 后端 WS 客户端

`server/services/strategy/quote_consumer.py::QuoteConsumer` MUST：

- 启动时读 `HQ_WS_URL` env（默认 `ws://localhost:8765/ws/quote`）
- 用 `websockets` 库建立 client 连接
- 维护 `latest_price: Dict[str, float]` + 每活跃 stock_code 的 TickBuffer
- tick 到达 → fan-out 到对应 StrategyEngine.evaluate_tick
- 断线时指数退避重连：1s → 2s → 4s → ... → max 30s
- 60s 无 tick → warn log（不开新连接）
- 健康心跳：每 30s log 当前已订阅 stock_code 数 + buffer 占用

#### Scenario: 启动后正常接收 tick

- **WHEN** QuoteConsumer 启动 + 1 个 strategy 订阅 600519.SH
- **AND** hqserver 推 `{code: '600519.SH', last_price: 1820.5, ...}`
- **THEN** QuoteConsumer 更新 latest_price['600519.SH']=1820.5 + 调对应 StrategyEngine.evaluate_tick

#### Scenario: 连接断开自动重连

- **WHEN** hqserver 重启 / 网络中断
- **THEN** QuoteConsumer MUST 按 1s/2s/4s/.../30s 指数退避重连，无限重试，每次重连成功 log INFO

#### Scenario: STRATEGY_ENGINE_ENABLED=false 不启动

- **WHEN** `.env` 中 `STRATEGY_ENGINE_ENABLED=false`
- **THEN** QuoteConsumer MUST NOT 创建 asyncio task，所有 strategy 端点返 503

### REQ-STRAT-008: REST API CRUD + 控制

`server/api/strategy.py` 提供以下端点，全部需要 login（`/api/strategy/flags/definitions` 任意登录用户可调；其他端点需 `trader` 或 `admin`）：

| Method | Path | Body | 说明 |
|---|---|---|---|
| GET | `/api/strategy/` | - | 当前 user 的所有策略（含嵌套 regimes + grids） |
| POST | `/api/strategy/` | `StrategyCreate` | 创建策略（含嵌套 regimes + grids，事务） |
| GET | `/api/strategy/{id}` | - | 单个策略详情 |
| PUT | `/api/strategy/{id}` | `StrategyUpdate` | 更新策略（含嵌套 regimes 增删改 + grids 增删改） |
| DELETE | `/api/strategy/{id}` | - | 删除策略（cascade） |
| POST | `/api/strategy/{id}/control` | `{action: 'pause'\|'resume'\|'stop'\|'clear_now'}` | 控制策略状态 |
| GET | `/api/strategy/{id}/audit?trd_date=YYYYMMDD` | - | 查询当日 audit（前 200 条） |
| GET | `/api/strategy/flags/definitions` | - | 标志注册表（前端下拉数据） |

所有端点 MUST 首部检查 `STRATEGY_ENGINE_ENABLED`，未启用返 503 `{code: ENGINE_DISABLED, msg: 'strategy engine is disabled'}`。

#### Scenario: 创建策略含嵌套 regimes + grids

- **WHEN** POST /api/strategy/ body 含 1 个 strategy + 2 个 regimes + 4 个 grids（regime1 含 2 grids）
- **THEN** 4 张表事务提交，返 strategy id，外键关系正确建立

#### Scenario: 普通用户调 POST /api/strategy/ 拒绝

- **WHEN** role=user（非 trader/admin）调 POST /api/strategy/
- **THEN** 返 403 `{detail: '需要 trader 或 admin 权限'}`

#### Scenario: 控制 action=clear_now 立即清仓

- **WHEN** POST /api/strategy/5/control {action: 'clear_now'}
- **AND** Strategy(id=5).status='active'
- **THEN** engine MUST 在下一 tick 评估时强制 plan_clear(position_vol)（临时覆盖 regime 选择），audit 记 `trigger_type='manual_clear'`，完成后 strategy.status='stopped'

#### Scenario: 删除策略 cascade

- **WHEN** DELETE /api/strategy/5
- **THEN** Strategy(id=5) + 所有关联 StrategyRegime + StrategyGrid + StrategyAudit 全部删除（FK ON DELETE CASCADE）

#### Scenario: 审计查询按日期过滤

- **WHEN** GET /api/strategy/5/audit?trd_date=20260705
- **THEN** 返 trd_date='20260705' 的 audit rows，按 created_at DESC 排序，最多 200 条

### REQ-STRAT-009: WS 频道 `strategy_update`

后端 MUST 在以下事件触发时 broadcast WS 频道 `strategy_update`，payload schema：

```json
{
  "type": "regime_changed" | "grid_triggered" | "grid_rejected" | "manual_clear" | "engine_state",
  "strategy_id": int,
  "stock_code": str,
  "regime_id": int | null,
  "regime_name": str | null,
  "from_regime_id": int | null,
  "from_regime_name": str | null,
  "trigger_grid": {direction, step_offset, trigger_price, volume} | null,
  "current_price": float | null,
  "position_vol": int | null,
  "base_volume": int | null,
  "order_no": str | null,
  "reject_reason": str | null,
  "ts": ISO8601
}
```

#### Scenario: regime 切换广播

- **WHEN** engine 从 R1 切换到 R2
- **THEN** MUST broadcast `strategy_update {type: 'regime_changed', from_regime_id: 1, regime_id: 2, ...}`

#### Scenario: 网格触发广播

- **WHEN** engine 下单成功
- **THEN** MUST broadcast `strategy_update {type: 'grid_triggered', trigger_grid, order_no, ...}`（order_no 是 broker 返回的本地 8 位序号）

#### Scenario: 拒触发广播（含原因）

- **WHEN** sell grid 被底仓保护拒触发
- **THEN** MUST broadcast `strategy_update {type: 'grid_rejected', reject_reason: 'base_floor_protected', ...}`

### REQ-STRAT-010: Order.user_def = strategy.id 关联（Strategy 是总表）

`Strategy` 表是管理策略的**总表**（顶层实体）。所有该策略产生的订单 MUST `Order.user_def = str(strategy.id)`（裸 strategy_id 作 key，无 'STRATEGY:' 前缀），作为 Order → Strategy 的外键关联字段。

**`Order.user_def` 字段语义汇总**：
- `user_def = ''` — 普通手动单（无任何标签）
- `user_def = 'T0'` — 手动 T0 标签（沿用 REQ-TRADE-006）
- `user_def = 'CANCEL:{orig_order_no}'` — 撤单 audit row（沿用 REQ-TRADE-003 §v9）
- `user_def = str(strategy.id)` — 策略引擎单（新增本 change）

**索引**：Order 表 MUST 加 `Index("ix_orders_user_def", "user_def")`（普通 INDEX，无 UNIQUE），支撑 `WHERE user_def = '<id>'` 关联查询性能。

#### Scenario: strategy 单在 Order 表可识别

- **WHEN** 策略引擎调 `ord_stk(...)` 提交买单，strategy.id=5
- **THEN** Order.user_def MUST = `'5'`（`str(strategy.id)`），无前缀
- **AND** 通过 `WHERE orders.user_def = '5'` 可检索该策略全部订单
- **AND** 通过 `JOIN strategy ON orders.user_def = CAST(strategy.id AS TEXT)` 可 JOIN 策略元数据

#### Scenario: 手动 vs 策略下单互不污染

- **WHEN** trader 手动下单 user_def='T0'
- **AND** 策略引擎同时下单 user_def='5'（strategy.id=5）
- **THEN** 两条 Order 在数据库共存
- **AND** 「策略 5 订单」查询 `WHERE user_def = '5'` 仅命中策略单，不含 T0 单

#### Scenario: 策略单撤单 audit

- **WHEN** 策略单（user_def='5'）被 trader 手动撤单
- **THEN** cancel-row 写入 user_def='CANCEL:{orig_order_no}'（沿用 REQ-TRADE-003 v9 约定），**不继承原 user_def='5'**
- **AND** 策略引擎下次评估按 broker 推送的 cancel-row status=54 重算 position_vol

#### Scenario: 索引性能

- **WHEN** 单策略订单数 > 10000 行
- **THEN** `WHERE user_def = '<id>'` 查询 MUST < 50ms（依赖 `ix_orders_user_def` 索引）

#### Scenario: 区分策略单 vs 普通单

- **WHEN** audit 页面要列「所有非策略订单」
- **THEN** SQL: `WHERE user_def NOT IN (SELECT CAST(id AS TEXT) FROM strategy) AND user_def NOT LIKE 'CANCEL:%' AND user_def != 'T0'`

### REQ-STRAT-011: 下单并发限制

策略引擎对同一 strategy 的所有 actions MUST 串行执行（单 asyncio.Lock），避免同一 tick 内多 grid 同时下单导致 race condition。

#### Scenario: 单 tick 多 action 串行

- **WHEN** 1 个 tick 内 plan 出 [sell 100, buy 200]
- **THEN** engine MUST 先 await ord_stk(sell) 完成 → 再 await ord_stk(buy)，串行而非并发

### REQ-STRAT-012: 前端 `/strategy-trade` 视图

`client/src/views/StrategyTrade.vue` MUST 渲染：

- 左侧：策略列表（按 status 分组：active / paused / stopped / finished）+ 「新建策略」按钮
- 中部：选中策略的 StrategyConfig + RegimeEditor 表单
- 右侧：StrategyMonitor 实时面板（当前 flags chips + 当前 regime name + 触发倒序 audit 50 条 + 控制按钮 pause/resume/stop/clear_now）
- 底部：当日 audit 全量表（按时间倒序，可滚动加载）

路由 `/strategy-trade`，meta.roles = `['trader', 'admin']`，沿用现有 vue-router 守卫。

#### Scenario: 路由守卫拦截 user 角色

- **WHEN** role=user 访问 /strategy-trade
- **THEN** router 重定向到 /403 或登录页（沿用既有 RBAC 守卫）

#### Scenario: STRATEGY_ENGINE_ENABLED=false 时的 UX

- **WHEN** 后端启用开关为 false，前端调用任意 strategy API 返 503
- **THEN** StrategyTrade.vue MUST 显示「策略引擎未启用」提示横幅 + 禁用所有「新建」「启用」按钮，但允许查看历史 audit

### REQ-STRAT-013: 前端组件边界

`client/src/modules/strategy/` MUST 单一对外入口 `index.js`（re-export 6 个组件 + 2 个 composable），严禁其它模块深层路径引入其内部文件。

`StrategyTrade.vue` MUST NOT import 任何 T0Trade 相关 composable / 组件（保持模块独立）。

#### Scenario: 模块边界校验

- **WHEN** Grep `StrategyTrade.vue` 含 `from.*t0` 或 `from.*T0Trade`
- **THEN** MUST 0 命中（lint 规则或人工 review 兜底）

### REQ-STRAT-014: T0 端点集成（type='t0' 策略与现有 T0 端点互通）

由于 `Strategy.type='t0'` 策略的下单 `user_def = str(strategy.id)`（**不**用 `'T0'`），现有 T0 端点 MUST 同步修改以 JOIN `strategy` 表过滤。

**改造的端点**：
- `GET /api/orders/t0-stats/{stock_code}?t0_only=true` — JOIN `strategy` ON `Order.user_def = CAST(strategy.id AS TEXT)` WHERE `strategy.type = 't0'`，**union** `Order.user_def = 'T0'`（兼容手动 T0 单）
- `GET /api/orders/t0-trades/{stock_code}` — 同上
- `GET /api/orders/t0-exposure?trd_date=YYYYMMDD` — 同上
- `GET /api/orders/t0-aggregate?days=30` — 同上

**实现位置**：`server/services/t0_aggregate.py::apply_user_def_filter` 入参从 `user_def='T0'` 扩展为支持 `(user_def='T0' OR strategy_type='t0')` 双条件。

#### Scenario: T0 策略单被 t0-stats 统计

- **WHEN** Strategy(id=5, type='t0', stock_code='600519.SH') + 该策略当天下单 5 笔 (user_def='5')
- **AND** 同时手动 T0Trade.vue 下单 3 笔 (user_def='T0')
- **AND** 调用 `GET /api/orders/t0-stats/600519.SH?t0_only=true`
- **THEN** 返 stats MUST 含 5+3 = 8 笔委托 / 全部对应成交的 PnL
- **AND** 响应 schema 与改造前一致（无 BREAKING）

#### Scenario: 普通策略单不被 t0-stats 统计

- **WHEN** Strategy(id=6, type='general', stock_code='600519.SH') + 该策略当天下单 5 笔 (user_def='6')
- **AND** 调用 `GET /api/orders/t0-stats/600519.SH?t0_only=true`
- **THEN** stats MUST NOT 含这 5 笔（type='general' 不计入）

#### Scenario: t0-exposure 含 T0 策略单

- **WHEN** 同标的当日 1 个 T0 策略 + 1 个手动 T0 标签
- **AND** `GET /api/orders/t0-exposure?trd_date=20260705&user_def=T0`
- **THEN** 响应 positions[] MUST 含两类的合并净敞口（不区分来源）

#### Scenario: t0-aggregate 跨日聚合含 T0 策略单

- **WHEN** 过去 30 天内 Strategy(id=5, type='t0') 共触发 20 笔成交
- **AND** `GET /api/orders/t0-aggregate?days=30`
- **THEN** summary.trade_count MUST 含 20 笔（+ 手动 T0 笔数）

#### Scenario: 既有非 strategy 单保持兼容

- **WHEN** 历史手动 T0 单 (user_def='T0') 在 strategy 表创建前已存在
- **THEN** t0-stats / t0-exposure / t0-aggregate 端点 MUST 仍能统计这些历史单（向后兼容）

## Scenarios

### S-STRAT-001: 策略激活 + tick 触发 + 下单全链路

Given trader 已创建 Strategy(id=5, stock_code='600519.SH', reference_price=1820.0, base_volume=100)  
And Strategy 含 Regime(R1, priority=10, required_flags=['ma_bullish'], base_volume=200, clear_position=false)  
And R1 含 Grid(G1, direction=buy, step_offset=-10, trigger_price=1810, volume=100)  
And 当前 position.vol=300  
And QuoteConsumer 已订阅 600519.SH  
When hqserver 推 tick {code:'600519.SH', last_price:1808.0, ...}（MA5 > MA10 > MA20 + tick ≤ G1.trigger_price）  
Then TickBuffer 更新 + flags 检测 → active_flags ⊇ {ma_bullish}  
And match_regime → R1（required_flags 全到 + priority 最高）  
And plan_buy(G1, ...) → 100（无底仓保护，buy 不受影响）  
And engine 调 ord_stk({stock_code, order_type:23, volume:100, price:1808, user_def:str(strategy.id)})  
And Order 表写入 + audit 写入 trigger_type='grid_buy'  
And WS broadcast strategy_update {type:'grid_triggered', order_no, ...}

### S-STRAT-002: 卖单受底仓保护

Given Strategy(id=5, base_volume=100) + Regime(R1) + Grid(G2, direction=sell, trigger_price=1830, volume=300)  
And position.vol=250（仅 150 股可卖，100 股底仓）  
When hqserver 推 tick {last_price:1832.0}（达 sell 触发）  
Then plan_sell(G2, position_vol=250, base_volume=100) → 100（min(300, 150) → 整手 100）  
And engine 下卖单 100 股  
And audit 写入 trigger_type='grid_sell', order_no 关联  
And WS broadcast strategy_update {type:'grid_triggered'}

### S-STRAT-003: 手动清仓（含底仓）

Given Strategy(id=5, status='active', base_volume=100) + position.vol=500  
When trader 点「立即清仓」按钮 → POST /api/strategy/5/control {action:'clear_now'}  
Then engine 下一评估强制 plan_clear(500) → 下卖单 500 股  
And audit 写入 trigger_type='manual_clear'  
And Strategy.status='stopped'  
And WS broadcast strategy_update {type:'manual_clear', order_no, ...}

### S-STRAT-004: regime 切换 cooldown

Given Strategy 含 R1(priority=10) + R2(priority=20)  
And R1 当前 active，上次切换 ts=10:00:00  
When 10:02:00 active_flags 变化 → match_regime 命中 R2  
Then cooldown 生效，保持 R1 active（不切换）  
And audit 写入 trigger_type='regime_cooldown', from=R1, attempted=R2

## API Surface

| Method | Path | Auth | 说明 |
|---|---|---|---|
| GET | `/api/strategy/` | trader/admin | 列表 |
| POST | `/api/strategy/` | trader/admin | 创建 |
| GET | `/api/strategy/{id}` | trader/admin | 详情 |
| PUT | `/api/strategy/{id}` | trader/admin | 更新 |
| DELETE | `/api/strategy/{id}` | trader/admin | 删除 |
| POST | `/api/strategy/{id}/control` | trader/admin | 控制（pause/resume/stop/clear_now） |
| GET | `/api/strategy/{id}/audit?trd_date=YYYYMMDD` | trader/admin | audit 查询 |
| GET | `/api/strategy/flags/definitions` | login | 标志注册表 |
| WS | `strategy_update` | login | 实时事件推送 |

## Known Issues (v1 已知边界)

- ⚠️ 单策略单标的（多标的并行下个 change）
- ⚠️ 标志阈值不可自定义（v1 用经验值，v2 加阈值配置）
- ⚠️ 无回测 / 模拟盘（v2 加）
- ⚠️ 跨日 audit 不自动归档（依赖日初 reconcile 清理旧 row，跨日持久化下个 change）
- ⚠️ 同 (user, stock_code, type) 唯一 active 策略（不同 type 可并存；跨策略资金调度冲突 v2 加）
- ⚠️ 9 种标志固定（v1 后端硬编码，v2 开放自定义注册）
- ⚠️ type='t0' 策略需要现有 T0 端点 JOIN strategy 改造（task 8 已规划，零 BREAKING 响应 schema）