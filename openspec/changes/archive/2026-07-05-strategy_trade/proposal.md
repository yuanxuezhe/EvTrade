# strategy_trade — 网格策略交易引擎

## Why

T0Trade 解决「人工轮动 + 单笔下单」，但 trader 在震荡市 / 趋势市切换时仍需手工切换参数；缺少**按市场状态自动切换参数集**的能力，导致两类典型亏损：

1. **震荡市用宽网格** → 频繁假突破触发，磨损手续费
2. **趋势市用窄网格** → 单边行情只吃到一段，没让利润奔跑

需求：在新增的 `/strategy-trade` 页面，让 trader 给单只标的配置**多档「参数集 (regime)」**，每档绑定一组**量价标志 (flags)**（如 MACD 金叉、RSI 超买、量能突破、均线多头）。策略引擎订阅 hqserver 行情推送，实时计算标志、匹配当前应启用的参数集（含优先级）、按该参数集的网格配置下单。

**核心约束（必须严格满足）**：
- **底仓保护**：策略卖单绝不允许把持仓打到 `base_volume` 以下。`base_volume` 是保留底仓，每档参数集可独立覆盖。
- **清仓标志**：某档参数集可设 `clear_position=true`，激活时跳过底仓保护，全部卖出（含底仓）。这是底仓保护机制的**唯一合法打破路径**。

## What Changes

### 新 capability：`strategy`

**后端**：
- 新增 `server/services/strategy/` 包（沿用 `services/t0/` facade 模式）：
  - `models.py` — SQLAlchemy ORM：`Strategy` / `StrategyRegime` / `StrategyGrid` / `StrategyAudit`
  - `repository.py` — DB CRUD
  - `indicators.py` — 纯函数指标计算（MA / RSI / 量能 / 价格变化率，基于滚动 100-tick buffer）
  - `flags.py` — 标志检测器（基于 indicators，输出 `{code: bool}` 字典）
  - `regime.py` — 参数集匹配（priority + required_flags AND + exclude_flags NOT）
  - `grid.py` — 网格决策（含底仓保护、整手取整、单次触发量钳制）
  - `engine.py` — 单标的评估入口（绑定 stock_code → indicator buffer + flag 检测 + regime 匹配 + grid 决策 + audit）
  - `quote_consumer.py` — **后端首次接入** hqserver WS（`HQ_WS_URL`），维护 `latest_price: Dict[str, float]`，tick 到达 fan-out 到活跃 engine
  - `audit.py` — 触发审计日志写入
- 新增 `server/api/strategy.py` — REST 路由（CRUD + 控制 + 审计查询），facade re-export 给 test monkeypatch
- DB 加 4 张表（见 `design.md` §Schema）

**前端**：
- 新增 `client/src/views/StrategyTrade.vue` 主视图（路由 `/strategy-trade`）
- 新增 `client/src/modules/strategy/` 模块（沿用 `t0-trade-polish-bundle` 的 feature-group 模式）：
  - `index.js` — 公共入口
  - `StrategyConfig.vue` — 创建 / 编辑策略基本信息
  - `RegimeEditor.vue` — 参数集编辑（标志勾选 + 优先级 + 网格列表）
  - `GridEditor.vue` — 网格编辑（方向 / 步长 / 数量 / 最大触发次数）
  - `FlagPicker.vue` — 标志选择器（下拉 + 简短说明）
  - `StrategyMonitor.vue` — 实时监控面板（当前标志 / 当前 regime / 触发历史）
- 新增 `client/src/stores/strategy.js` Pinia 仓库 + `client/src/api/strategy.js` REST 客户端
- 路由加 `/strategy-trade` + 角色守卫（trader / admin 可访问）

**v1 标志注册表**（后端硬编码，前端下拉选择）：
- `ma_bullish` — MA5 > MA10 > MA20（均线多头排列）
- `ma_bearish` — MA5 < MA10 < MA20（均线空头排列）
- `rsi_overbought` — RSI(6) ≥ 70
- `rsi_oversold` — RSI(6) ≤ 30
- `vol_breakout` — 当根成交量 ≥ 2× 过去 20 根均量
- `price_change_up` — 当根涨幅 ≥ +1%
- `price_change_down` — 当根跌幅 ≤ -1%
- `macd_golden_cross` — DIF 上穿 DEA（v1 简化为：DIF > DEA 且 1 根前 DIF ≤ DEA）
- `macd_death_cross` — DIF 下穿 DEA

**v1 范围内**：
- 单策略单标的（多标的并行下个 change）
- 评估在 tick 触发（事件驱动，0 轮询）
- 触发即下单（不延迟、不聚合）
- 持仓查询走 `cachedAsset` / `positions` store（已有，不重写）
- **`Strategy` 是管理策略的总表**（顶层实体）。所有该策略产生的订单 `Order.user_def = str(strategy.id)`（裸 key，无前缀），与 `user_def='T0'` / `'CANCEL:{no}'` 同字段复用，靠 JOIN `strategy` 表区分语义
- **Strategy.type 区分**：`Strategy.type ∈ {'general', 't0'}`，区分普通策略 vs T0 策略；user_def 写入规则统一为 `str(strategy.id)`（type='t0' 也不例外），T0 端点改为 JOIN strategy WHERE type='t0'

**v1 范围外（后续 change）**：
- 多标的组合策略 / 跨标的资金调度
- 回测 / 模拟盘（用历史 tick 重放）
- 策略间优先级 / 资金分配冲突解决
- 机器学习标志 / 自定义指标

### Modified Capabilities

| Cap | 修改内容 |
|---|---|
| `trading` | REQ-TRADE-011 新增：策略引擎下单 `user_def=str(strategy.id)`（裸 strategy_id 作 key，含 type='t0' 策略也用此约定），与现有 `user_def='T0'`（手动）/ `'CANCEL:{no}'` 同字段复用；同时给 `orders.user_def` 加索引（IX_ORDERS_USER_DEF）支撑关联查询；T0 端点（t0-stats/t0-exposure/t0-aggregate）同步改为 JOIN strategy WHERE type='t0' |
| `frontend` | REQ-FE-300 新增：路由表加 `/strategy-trade`，角色守卫 `trader`/`admin` |
| `quotes` | REQ-QUOTE-003 新增：后端通过 `HQ_WS_URL` 接入 hqserver WS，独立于前端直连（不破坏既有 hqserver 推送契约） |
| `push` | REQ-PUSH-007 新增：新增 WS 频道 `strategy_update`，广播策略触发事件（regime 切换 / 网格触发 / 拒触发原因） |
| `configuration` | REQ-CFG-008 新增：env `STRATEGY_ENGINE_ENABLED`（默认 false）+ `HQ_WS_URL`（默认 `ws://localhost:8765/ws/quote`） |

## Impact

**新增文件**：
- 后端：`server/services/strategy/{__init__,models,repository,indicators,flags,regime,grid,engine,quote_consumer,audit}.py`（10 个文件，单文件 ≤200 行）
- 后端 API：`server/api/strategy.py`（单文件，~180 行；phase-2 按需再拆）
- 前端视图：`client/src/views/StrategyTrade.vue`（~250 行内）
- 前端模块：`client/src/modules/strategy/{index.js,StrategyConfig.vue,RegimeEditor.vue,GridEditor.vue,FlagPicker.vue,StrategyMonitor.vue}`（6 个文件，单文件 ≤200 行）
- 前端 composable：`client/src/modules/strategy/composables/{useStrategy,useFlagDefinitions}.js`
- 前端 store + API：`client/src/stores/strategy.js`、`client/src/api/strategy.js`
- 单测：`server/tests/strategy/{test_indicators,test_flags,test_regime,test_grid,test_engine}.py`、`client/tests/views/StrategyTrade.test.js`、`client/tests/modules/strategy/*`
- OpenSpec：`openspec/specs/strategy/spec.md`（新 capability）

**修改文件**：
- `server/main.py` — 注册 `strategy.router` + 启动 `quote_consumer`（受 `STRATEGY_ENGINE_ENABLED` 控制）
- `server/db/tables.py` — 注册 4 张新 ORM
- `server/models/orm.py` — Order 表加 `Index("ix_orders_user_def", "user_def")` 索引
- `server/api/t0_stats.py` — t0-stats / t0-trades 端点改 JOIN strategy WHERE type='t0'
- `server/api/t0_aggregate.py` — t0-exposure / t0-aggregate 端点改 JOIN strategy WHERE type='t0'
- `server/services/t0_aggregate.py` — `apply_user_def_filter` 扩展支持 `strategy_type='t0'` 双条件
- `client/src/router/index.js` — 加路由
- `client/src/api/index.js`（或各 store） — 引入 strategy 模块
- `openspec/specs/{trading,frontend,quotes,push,configuration}/spec.md` — 各加 1 段 REQ delta

**不动**：
- `server/rpc/client.py`（msgpacket RPC 客户端契约零改动）
- `server/api/orders/*`（策略引擎复用 `ord_stk`，零侵入）
- `hq/hqserver.py`（后端作为新 WS 客户端接入，hqserver 不感知）
- 现有 8 个 capability 的核心数据契约

**测试覆盖**：
- 后端：`test_indicators` 12 用例（rolling buffer 边界）+ `test_flags` 8 用例 + `test_regime` 10 用例（含优先级 + AND + NOT）+ `test_grid` 12 用例（底仓保护 / 整手 / clear_position）+ `test_engine` 8 用例（合成 tick 驱动）
- 前端：`StrategyTrade.test.js` 12 用例（mountView 路径）+ `RegimeEditor.test.js` 8 用例 + `GridEditor.test.js` 6 用例
- 集成：手动起 backend + hqserver mock WS，验证 tick → engine → ord_stk → audit 全链路

**回滚**：4 张新表无外部消费者，回滚 = revert commit + drop tables。零迁移成本。

**部署开关**：`STRATEGY_ENGINE_ENABLED=false` 时 quote_consumer 不启动、router 返 503，trader 完全无感。**灰度上线**安全。