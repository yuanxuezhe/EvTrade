# tasks.md — strategy_trade

按依赖顺序拆 11 个 commit。每 commit 可独立 revert，单文件 < 250 行。

## 1. DB schema + SQLAlchemy models（commit: feat(server): strategy 4 张 ORM + 表创建）

- [x] 1.1 新建 `server/services/strategy/__init__.py`（空 facade，~10 行）
- [x] 1.2 新建 `server/services/strategy/models.py`（~120 行）：4 张表 ORM（Strategy / StrategyRegime / StrategyGrid / StrategyAudit），含 JSON 字段序列化（required_flags / exclude_flags / action_payload）。**Strategy 含 `type VARCHAR(16) NOT NULL DEFAULT 'general'`**（'general' / 't0'）
- [x] 1.3 在 `server/db.py::init_db` 加 `from server.services.strategy import models as strategy_models` 触发 ORM 注册
- [x] 1.4 在 `server/models/orm.py` 给 Order 表加 `Index("ix_orders_user_def", "user_def")`；`server/db.py::init_db` 加 `CREATE INDEX IF NOT EXISTS ix_orders_user_def ON orders(user_def)` 幂等迁移
- [x] 1.5 在 `Strategy` 表加 `Index("ix_strategy_type", "type")`（支撑 T0 端点 JOIN 过滤）
- [x] 1.6 单测：`server/tests/strategy/test_models.py`（6 用例全过：tables/indexes 注册 + cascade 配置 + JSON round-trip + Order 新索引）
- [x] 1.7 验证：`python -m pytest server/tests/strategy/test_models.py -v` 6 passed

## 2. repository 层（commit: feat(server): strategy repository CRUD）

- [x] 2.1 新建 `server/services/strategy/repository.py`（~180 行）：`create_strategy / get_strategy / list_strategies / update_strategy / delete_strategy` + 同理 regime / grid / audit
- [x] 2.2 单测：`server/tests/strategy/test_repository.py`（~80 行，7 用例：基础 CRUD + cascade + JSON 字段 round-trip；**db fixture 加 truncate 4 张表保隔离**）
- [x] 2.3 验证：`pytest server/tests/strategy/test_repository.py` 全过（7 passed）

## 3. indicators 纯函数层（commit: feat(server): strategy indicators MA/RSI/量能/MACD）

- [x] 3.1 新建 `server/services/strategy/indicators.py`（~260 行）：
  - `@dataclass(frozen=True) IndicatorParams`（ma_periods / rsi_period / macd_fast/slow/dea / vol_period，preset: standard / short_term / long_term）— **不写死，预留动态切换入口**
  - `class TickBuffer`（deque(maxlen=100)，append / last_n / last / prices / volumes / __len__）
  - 私有 `_sma` / `_ema`（标准 α）/ `_rsi_wilder`（α=1/N）
  - 公共 `compute_ma(prices, period)` / `compute_rsi(prices, period=6)` / `compute_macd(prices, params)` / `compute_vol_avg(volumes, period=20)`，全部返 Optional，buffer 不足 / NaN 返 None
- [x] 3.2 单测：`server/tests/strategy/test_indicators.py`（24 用例全过：buffer 4 + IndicatorParams 4 + MA 3 + RSI 5 + MACD 4 + Vol 3 + smoke 1）
- [x] 3.3 验证：`pytest server/tests/strategy/test_indicators.py` → 24 passed；全量 `pytest server/tests/strategy/` → 37 passed

## 4. flags 检测器（commit: feat(server): strategy flags 9 种注册表）

- [x] 4.1 新建 `server/services/strategy/flags.py`（~220 行）：
  - `@dataclass(frozen=True) FlagDef`（code / name / category / description）
  - `FLAG_REGISTRY: Dict[str, FlagDef]` — **9 种** flag（spec REQ-STRAT-002 共 9 项：ma_bullish/bearish, rsi_over/under, vol_breakout, price_change_up/down, macd_golden/death_cross）
  - `detect_flags(buffer, params=None, prev_close=None) -> Set[str]` — 调 indicators + 5 类检测器；buffer 不足或 prev_close 缺失静默跳过
  - `get_flag_definitions() -> List[Dict]` — 按 FLAG_REGISTRY 顺序返 [{code, name, category, description}, ...]
  - 私有 detect 函数：`_detect_ma_flags` / `_detect_rsi_flags` / `_detect_vol_flag` / `_detect_price_change_flags` / `_detect_macd_cross_flags`
  - 阈值常量：RSI 70/30、vol 2x、±1%
- [x] 4.2 单测：`server/tests/strategy/test_flags.py`（20 用例全过：registry 3 + MA 3 + RSI 3 + Vol 3 + Price 3 + MACD 3 + smoke 2）
- [x] 4.3 验证：`pytest server/tests/strategy/test_flags.py` → 20 passed；全量 `pytest server/tests/strategy/` → 57 passed

## 5. regime 匹配 + grid 决策（含底仓保护）（commit: feat(server): strategy regime 匹配 + grid 底仓保护）

- [x] 5.1 新建 `server/services/strategy/regime.py`（~100 行）：
  - `match_regime(regimes, active_flags) -> Optional[StrategyRegime]` — 5 条规则：enabled/required-AND/exclude-NOT/priority-DESC/id-ASC-tiebreak
  - `apply_cooldown(prev, candidate, last_switch_ts, now_ts, cooldown=300) -> bool` — 5 分支决策（首次/无候选/同 regime/冷却内/冷却外）
- [x] 5.2 新建 `server/services/strategy/grid.py`（~150 行）：
  - `@dataclass(frozen=True) GridAction`（direction / volume / trigger_price / grid_id / reject_reason）
  - `plan_buy(grid, current_price) -> Optional[GridAction]` — 价格触发 + max_fires 检查
  - `plan_sell(grid, position_vol, base_volume) -> Optional[GridAction]` — **核心：底仓保护 + 整手取整** + max_fires 检查
  - `plan_clear(position_vol) -> GridAction`（regime.clear_position=True 时调）
  - `evaluate_grids(grids, current_price, position_vol, base_volume, clear_position=False) -> List[GridAction]` — sell 优先排序；clear_position 插入首位
  - 常量 `LOT_SIZE=100`
- [x] 5.3 单测：`server/tests/strategy/test_regime.py`（12 用例全过）+ `server/tests/strategy/test_grid.py`（21 用例全过，覆盖 spec 全部 4 个 Scenario + 边界）
- [x] 5.4 验证：`pytest server/tests/strategy/test_regime.py server/tests/strategy/test_grid.py` → 33 passed；全量 `pytest server/tests/strategy/` → 92 passed

## 6. engine 评估入口 + audit（commit: feat(server): strategy engine 主入口 + 触发审计）

- [x] 6.1 新建 `server/services/strategy/audit.py`（~50 行）：`write_audit(db, strategy_id, trigger_type, ...)` wrapper，自动 commit + 默认 trd_date 当日
- [x] 6.2 新建 `server/services/strategy/engine.py`（~280 行）：
  - `STRATEGY_WS_CHANNEL = "strategy_update"`（注册到 ws_manager.active_connections）
  - `@dataclass EvaluateResult`（strategy_id / active_flags / matched_regime_id / regime_switched / regime_cooldown_blocked / actions / audit_ids / order_nos）
  - `class StrategyEngine`：TickBuffer + last_regime + last_switch_ts + IndicatorParams + prev_close 状态
  - `async evaluate_tick(tick, position_vol, base_volume, prev_close=None, now_ts=None, trd_date=None)` — 8 步流水线
  - `_execute_action`：单 GridAction → audit + (触发时) INSERT Order + ord_stk + UPDATE status + increment_fired_count
  - `_place_order`：仿 place.py 范式（status=48 → RPC → status=50/57；user_def=str(strategy.id)；remark=order_no）
  - `_broadcast`：strategy_update WS payload（regime_changed / grid_triggered / regime_cooldown）
  - DB 用 joinedload eager-load regimes+grids（防 session 关闭后 lazy load 崩盘）
- [x] 6.3 单测：`server/tests/strategy/test_engine.py`（8 用例全过：no_match / no_action / buy_trigger / sell_floor_protected / clear_position / regime_cooldown / sell_before_buy / smoke；mock ord_stk + ws_manager.broadcast）
- [x] 6.4 验证：`pytest server/tests/strategy/test_engine.py` → 8 passed；全量 `pytest server/tests/strategy/` → 100 passed；`python -c "from server.main import app"` OK

## 7. quote_consumer 后端 WS 接入（commit: feat(server): strategy 后端 WS 客户端接 hqserver）

- [x] 7.1 新建 `server/services/strategy/quote_consumer.py`（~340 行）：
  - `class QuoteConsumer`（asyncio 主循环 + websockets client + 重连退避 + health log）
  - 状态：`_engines: Dict[str, StrategyEngine]` + `_engine_id_map` + `_latest_price` + `_stop: asyncio.Event` + `_ws` + `_last_tick_ts` + `_tick_count`
  - 生命周期：`start()` / `stop()`（仿 RPClient）
  - `_main_loop()` → 重连 + asyncio.gather(consume_loop, health_loop)
  - `_connect()` 指数退避（1s → 2s → 4s → 8s → 16s → 30s cap）
  - `_consume_loop()` 解析 hqserver JSON → fan-out 到 engine.evaluate_tick
  - `_health_loop()` 30s 心跳 + 60s 无 tick 警告
  - `_load_engines()` DB 读 status='active' strategies + `_load_prev_close()` 从 QuoteSnapshot 灌入
  - `_get_position_for_stock()` + `_get_base_volume_for_stock()`（v1 简化为 DB 查）
  - `subscribe_strategy()` / `unsubscribe_strategy()` 本地字典管理（hqserver 无 subscribe）
  - 模块级 singleton：`_quote_consumer` + `get_quote_consumer()` / `close_quote_consumer()`
- [x] 7.2 `server/config.py` 加 2 env：`STRATEGY_ENGINE_ENABLED`（bool，默认 false）+ `HQ_WS_URL`（str，默认 `ws://127.0.0.1:8765`）
- [x] 7.3 `server/main.py` 加 2 个 startup/shutdown hook（受 STRATEGY_ENGINE_ENABLED 控制）
- [x] 7.4 `server/services/strategy/__init__.py` re-export QuoteConsumer + lifecycle
- [x] 7.5 `server/requirements.txt` 加 `websockets>=9.0,<11.0`
- [x] 7.6 单测：`server/tests/strategy/test_quote_consumer.py`（~210 行，7 用例）：
  - `_parse_tick` 正确解析 hqserver JSON
  - `_parse_tick` 静默忽略非 quote_update / 缺字段 / 非法 JSON
  - `_fanout_tick` 路由到匹配 stock_code 的 engine
  - `_fanout_tick` 丢弃未订阅 stock（仍记录 _latest_price）
  - `_load_engines` 从 DB 读 active strategies + QuoteSnapshot 注入 prev_close
  - `_connect` 指数退避序列 1→2→4→8→16→30
  - 模块级 singleton get/close 生命周期
- [x] 7.7 验证：`pytest server/tests/strategy/` → 107 passed；`python -c "from server.main import app"` OK

## 8. T0 端点迁移：JOIN strategy WHERE type='t0'（commit: refactor(server): t0 端点从 user_def='T0' 改 JOIN strategy type='t0'）

- [x] 8.0 `server/services/t0/aggregators.py` 加 `resolve_t0_user_defs(db, user_def) -> Optional[Set[str]]` helper；`apply_user_def_filter` 加 `db=None` 参数调用 helper（向后兼容）
- [x] 8.1 `server/api/t0_stats.py::t0_stats`：`Order.user_def == "T0"` 改为 `Order.user_def.in_(resolve_t0_user_defs(db, "T0"))`（包含 'T0' literal + 所有 type='t0' strategy id）
- [x] 8.2 `server/api/t0_stats.py::t0_history`（spec 误写为 t0_trades）：同上用 `resolve_t0_user_defs` 改造
- [x] 8.3 `server/api/t0_aggregate.py::t0_exposure`：调用 `apply_user_def_filter(..., db=db)` 让其内部解析 T0 union
- [x] 8.4 `server/api/t0_aggregate.py::t0_aggregate`：同上
- [x] 8.5 单测：`server/tests/strategy/test_t0_endpoint_migration.py`（~250 行，11 用例）：
  - `resolve_t0_user_defs` 空 / 'T0' 含 strategy ids / 其他字面（3）
  - `apply_user_def_filter` db 联合 + 旧无 db 兼容（2）
  - 端点：t0-stats t0_only true/false + t0-history + t0-exposure + t0-aggregate + schema 不变（6）
- [x] 8.6 验证：`pytest server/tests/strategy/test_t0_endpoint_migration.py` 11 passed + `pytest server/test_t0*.py server/tests/strategy/` 145 passed

## 9. REST API + 灰度开关（commit: feat(server): strategy REST CRUD + 控制 + 审计查询）

- [x] 9.1 新建 `server/api/strategy/` 子包（拆 3 文件避免 250 行硬约束）：
  - `__init__.py` (~17 行)：APIRouter(prefix="/api/strategy") + register_endpoints
  - `schemas.py` (~125 行)：GridSchema / RegimeSchema / StrategyOut / StrategyCreate / StrategyUpdate / ControlRequest / AuditRecord / FlagDefinition
    - JSON 字段用 `@validator(pre=True)` 兼容 ORM 原始字符串 / list 输入
    - datetime 字段用 Optional[datetime]（FastAPI jsonable_encoder 自动转 ISO）
  - `endpoints.py` (~215 行)：8 个端点 + helpers（_require_engine_enabled / _load_strategy_owned / _qc_subscribe / _qc_unsubscribe）
- [x] 9.2 `server/main.py` 注册 router（依赖 `get_current_user`）
- [x] 9.3 单测：`server/tests/strategy/test_api.py`（~270 行，15 用例）：
  - 灰度：enable/disable 返回 503/200（2）
  - CRUD：list/create/detail/update/delete（5）
  - 鉴权：other_trader 403 / admin 全访问 / unauthenticated 401（3）
  - 控制：pause/resume/stop + clear_now audit + invalid action 400（3）
  - audit 查询：trd_date 过滤（1）
  - flags：9 条注册 + 不受灰度门控（2）
- [x] 9.4 验证：`pytest server/tests/strategy/test_api.py` 15 passed；`pytest server/tests/strategy/` 122 passed；全量策略 + T0 160 passed；`from server.main import app` OK

## 10. 前端 API 客户端 + Pinia store（commit: feat(client): strategy store + API 客户端）

- [x] 10.1 新建 `client/src/api/strategy.js`（~100 行，104 实测）：`listStrategies / createStrategy / updateStrategy / deleteStrategy / controlStrategy / queryAudit / getFlagDefinitions`
- [x] 10.2 新建 `client/src/stores/strategy.js`（拆 2 文件保 ≤250）：`strategy.js`（229 行 Pinia facade）+ `strategy_helpers.js`（74 行 helpers：createPendingTracker / upsert / remove / audit helpers）
- [x] 10.3 单测：`client/tests/stores/strategy.test.js`（~200 行，9 用例：拉列表/过滤/单条/CRUD + pending/control+clear_now 边界/flags+分组/audit+appendAudit）
- [x] 10.4 验证：`npm test -- --run tests/stores/strategy.test.js` 9 passed

## 11. 前端模块组件（commit: feat(client): strategy modules 配置/编辑/监控组件）

- [x] 11.1 新建 `client/src/modules/strategy/index.js`（19 行）：re-export 5 子组件 + 2 composable
- [x] 11.2 新建 `client/src/modules/strategy/composables/useStrategy.js`（96 行）：CRUD wrapper + status/type 映射常量
- [x] 11.3 新建 `client/src/modules/strategy/composables/useFlagDefinitions.js`（42 行）：缓存 + reactive list + groupByCategory
- [x] 11.4 新建 `client/src/modules/strategy/StrategyConfig.vue`（156 行）：stock_code / type radio / ref_price / base_volume / note
- [x] 11.5 新建 `client/src/modules/strategy/FlagPicker.vue`（183 行）：按 category 分组 + 互斥 disabled + description popover
- [x] 11.6 新建 `client/src/modules/strategy/RegimeEditor.vue`（228 行）：name / priority / required+exclude flag / base_volume / clear_position + 嵌套 GridEditor 列表
- [x] 11.7 新建 `client/src/modules/strategy/GridEditor.vue`（162 行）：direction / trigger_price / step_offset / volume / max_fires / fired_count / enabled / priority + 删除
- [x] 11.8 新建 `client/src/modules/strategy/StrategyMonitor.vue`（212 行）+ 拆出 `StrategyRegimeList.vue`（152 行）+ `StrategyAuditTable.vue`（116 行）：title + type/status badge + 控制按钮 + regime collapse + audit 倒序 50 条
- [x] 11.9 单测：`RegimeEditor.test.js`（8 用例）+ `GridEditor.test.js`（6 用例，实测 7 含 read-only mirror 用例）+ `StrategyMonitor.test.js`（6 用例，stub 子组件以断言 props）
- [x] 11.10 验证：`npm test -- --run tests/modules/strategy/` 21 passed；全量 311/312 pass（1 个 pre-existing HistoryOrders 日期用例与本次无关）

## 12. 主视图 + 路由 + WS 频道接入（commit: feat(client): StrategyTrade.vue + 路由 + strategy_update WS 接入）

- [x] 12.1 新建 `client/src/views/StrategyTrade.vue`（228 行）+ 拆出 `useStrategyTrade.js`（175 行 composable）：左侧 StrategyList（按 type 分组 Tab：普通 / T0）+ StrategyConfig + RegimeEditor 表单区 + 右侧 StrategyMonitor 实时面板 + 底部 audit 表格
- [x] 12.2 `client/src/router/index.js` 加路由：`/strategy-trade` → `StrategyTrade.vue`，`meta.requiresTrader = true`（trader/admin 可访问）；旧 `/algo-strategy` redirect → `/strategy-trade`
- [x] 12.3 `client/src/stores/ws_dispatch.js` 加 `strategy_update` 频道处理：收到消息 → 包装为 AuditRecord → `store.appendAudit(strategy_id, trd_date, audit)`；缺 strategy_id 静默丢弃
- [x] 12.4 导航栏 `client/src/components/Sidebar.vue` 加入口（替换原 `/algo-strategy` 链接）
- [x] 12.5 单测：`client/tests/views/StrategyTrade.test.js`（12 用例全过：mountView 渲染 + tabs + select/create/cancelDraft/submit/save/delete + WS dispatch + type 切换）
- [x] 12.6 验证：`npm test -- --run` → 323/324 通过（1 个 pre-existing HistoryOrders 日期用例与本 change 无关）

**实施偏差**：原计划 12.1 单文件 ~240 行；实测拆为 StrategyTrade.vue (228) + useStrategyTrade.js (175) 两文件以保 ≤250 行约束。Sidebar.vue 文件路径实际为 `client/src/components/Sidebar.vue`（非 `layout/Sidebar.vue`）。

## 13. spec 同步 + 归档（commit: docs(openspec)）

- [x] 13.1 `openspec/specs/strategy/spec.md`（新 capability，281 行：13 REQ + 22 Scenario）创建
- [x] 13.2 `openspec/specs/trading/spec.md` 加 REQ-TRADE-011（Order.user_def = str(strategy.id) 关联约定 + IX_ORDERS_USER_DEF 索引 + T0 端点 JOIN 迁移说明）
- [x] 13.3 `openspec/specs/frontend/spec.md` 加 REQ-FE-310（策略交易路由 + 角色守卫 + WS 频道分发；原计划 REQ-FE-300 与 IDB 持久化段冲突，故用 310）
- [x] 13.4 `openspec/specs/quotes/spec.md` 加 REQ-QUOTE-005（后端 WS 接入；原计划 REQ-QUOTE-003 已存在「前端直连」，故用 005）
- [x] 13.5 `openspec/specs/push/spec.md` 加 REQ-PUSH-040（strategy_update 频道；原计划 REQ-PUSH-007 已存在「按 (activeTrdDate, order_no) 匹配」，故用 040）
- [x] 13.6 `openspec/specs/configuration/spec.md` 加 REQ-CFG-008（2 个新 env：STRATEGY_ENGINE_ENABLED + HQ_WS_URL）
- [x] 13.7 `openspec/.openspec.yaml` 加 strategy 能力域（specs 列表 + cross_references 4 条新关联）
- [x] 13.8 归档：`mv openspec/changes/strategy_trade openspec/changes/archive/2026-07-05-strategy_trade`

## 实施偏差备注

（实施过程中按实际情况调整后填入）

- task 13.3: FE REQ 编号用 310 而非 300，避免与 IDB 持久化段冲突
- task 13.4: QUOTE REQ 编号用 005 而非 003，003 已被「前端直连」占用
- task 13.5: PUSH REQ 编号用 040 而非 007，007 已被「按 (activeTrdDate, order_no) 匹配」占用
- 任何 spec 场景与实测不一致在此记录原因