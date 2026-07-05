# strategy — 网格策略交易引擎

> 📖 **DB schema** 详见 [`data-model/spec.md`](../data-model/spec.md) §4（Strategy / StrategyRegime / StrategyGrid / StrategyAudit）
> 📖 **接口契约** 详见 [`../../../docs/server-rest-api.md`](../../../docs/server-rest-api.md) §strategy

## Purpose

为单只标的配置**多档「参数集 (regime)」**，按实时行情**量价标志 (flags)** 自动切换参数集 + 按当前 regime 的网格配置自动下单。

**核心约束**：
- **底仓保护**：策略卖单不允许把持仓打到 `base_volume` 以下。`base_volume` 是保留底仓，每档 regime 可独立覆盖。
- **清仓标志**：regime 可设 `clear_position=true`，激活时跳过底仓保护，全部卖出（含底仓）。是底仓保护机制的**唯一合法打破路径**。

## Requirements

### REQ-STRAT-001: 策略 CRUD

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

## Cross References

- 行情来源：`quotes/spec.md` REQ-QUOTE-001（hqserver 推送）
- 委托下发：`trading/spec.md` REQ-TRADE-002（place 流程 + user_def 关联）
- WS 推送：`push/spec.md` REQ-PUSH-007（push_handlers 字段映射）
- 前端入口：`frontend/spec.md` REQ-FE-310（strategy-trade 路由 + 角色守卫）
- 配置：`configuration/spec.md` REQ-CFG-008（2 个新 env）