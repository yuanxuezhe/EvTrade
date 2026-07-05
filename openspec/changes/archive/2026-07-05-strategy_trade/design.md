# design.md — strategy_trade

## Context

**当前状态**：
- T0Trade.vue 是 trader 主导的手动轮动页，下单走 `POST /api/orders/place`
- 后端 FastAPI **不订阅行情**（AGENTS.md / `server/main.py:53-54` 明确："行情订阅已解耦到 hqserver"）
- 持仓查询走 Pinia `holdingsStore.cachedAsset / positions` + IDB write-through
- 下单后 broker `ord_cfm / trd_cfm` 走 RabbitMQ → `push_handlers` 写 DB → WS 推 Vue
- 现有 `t0_aggregate` 是只读统计计算，**没有**自动化下单引擎

**痛点**：
1. 震荡市 / 趋势市切换需 trader 手工调网格参数，反应慢、易误判
2. 单笔人工下单在快速行情下漏单率高
3. 没法同时跑多套参数集对比效果（策略 A vs 策略 B）

**约束**（沿用 CLAUDE.md + 现有架构）：
- 后端按 facade 包模式（`services/t0/` 已立）
- API 沿用 `register_place / register_cancel / register_query` 模式（test monkeypatch 友好）
- 单文件 ≤250 行、单函数 ≤40 行
- 前端按 feature 分组（`modules/<feature>/`，单一 index 入口）
- 业务数据本地 DB 优先（v4 改造后，orders/trades/positions/assets 本地）

## Goals / Non-Goals

### Goals
- 新增 `/strategy-trade` 视图，让 trader 给单标的配置多档参数集 + 多组网格
- 后端策略引擎事件驱动：hqserver tick → indicator buffer → flag 检测 → regime 匹配 → grid 决策 → 下单 → audit
- 严格底仓保护：卖单量 ≤ `position.vol - base_volume`（除非 `clear_position=true`）
- 标志注册表后端硬编码（v1 8 种），前端只读下拉，不开放阈值自定义
- 触发审计全留痕（每次评估无论触发与否都记 audit）
- WS 频道 `strategy_update` 广播 regime 切换 / 网格触发 / 拒触发原因
- 灰度开关：`STRATEGY_ENGINE_ENABLED=false` 时引擎停摆、API 返 503

### Non-Goals
- 多标的组合策略（v2）
- 历史回测 / 模拟盘（v2）
- 策略间资金调度冲突解决（v2）
- 自定义指标 / 自定义阈值（v2）
- 跨日持久化触发历史（仅当日，跨日归档下个 change）

## Decisions

### 1. 后端首次接入 hqserver WS（架构突破）

**新模块** `server/services/strategy/quote_consumer.py`：
- 启动时读 `HQ_WS_URL`（默认 `ws://localhost:8765/ws/quote`）
- 用 `websockets` 客户端库（已在 `pyproject.toml` 依赖，参考 `conftest.py` 验证）
- 维护 `latest_price: Dict[str, float]` + 每个活跃 stock_code 的 rolling buffer（最近 100 tick）
- tick 到达 → fan-out 给 `engine.evaluate_tick(stock_code, tick)`
- 断线重连：指数退避（1s → 2s → 4s → max 30s），无限重试
- 健康检查：60s 无 tick → warn log + 继续等待（不开新连接）

**Why 后端直连而不是 Vue 转发**：
- trader 关手机、关浏览器仍可触发（关键！脱机策略）
- tick 频率高时减少 frontend → backend HTTP 转发瓶颈
- 部署简单：backend 和 hqserver 同机房

**Alt considered**：
- Vue 转发：架构简单但 trader 切后台即失效
- RabbitMQ 订阅：hqserver 目前没往 MQ 推 quote（仅前端 WS），改造 hqserver 范围过大
- broker RPC `qry_snapshot` 轮询：延迟 1-2s，错过快速行情

### 2. Regime 匹配 = 优先级 + 必要标志 AND + 排除标志 NOT

```python
def match_regime(regimes: List[StrategyRegime], active_flags: Set[str]) -> Optional[StrategyRegime]:
    candidates = [
        r for r in regimes
        if r.enabled
        and set(r.required_flags).issubset(active_flags)
        and not (set(r.exclude_flags) & active_flags)
    ]
    if not candidates:
        return None
    # 取 priority 最高者；并列取 id 最小的（创建顺序在前）
    return max(candidates, key=lambda r: (r.priority, -r.id))
```

**Why priority 而非时间戳**：priority 显式可读、trader 易调；时间戳隐式易踩坑。

**Alt considered**：
- 「所有匹配 regime 合并 grids」→ 同方向冲突无法解（卖 100 vs 卖 200 同时触发听谁的）
- 「后注册的覆盖先注册的」→ 隐式行为，trader 难理解

### 3. 底仓保护算法

```python
def plan_sell(grid: StrategyGrid, position_vol: int, base_volume: int) -> Optional[int]:
    """返回应卖股数，None 表示拒触发（受底仓保护）"""
    if grid.direction != 'sell':
        return None
    protected_floor = base_volume
    available = position_vol - protected_floor
    if available <= 0:
        return None  # 已到底仓，不卖
    sell_vol = min(grid.volume, available)
    # 整手取整（卖向下到 100 的倍数）
    sell_vol = (sell_vol // 100) * 100
    return sell_vol if sell_vol > 0 else None
```

**关键不变式**：`position.vol ≥ strategy.base_volume` 在所有非 clear 场景下成立。

**clear_position 路径**：
```python
def plan_clear(position_vol: int) -> int:
    return position_vol  # 全部卖出，含底仓
```

**Why 在 grid 层而非 engine 层做底仓检查**：grid 层是单 grid 决策单元，逻辑纯净；engine 层只做组装 + 调 RPC，不重复校验。

### 4. 评估触发 = tick 驱动 + 整批

每次 tick 触发 `engine.evaluate_tick(stock_code, tick)`：
1. 更新 indicator buffer（`indicators.update(buffer, tick)`）
2. 重算 flags（`flags.detect(buffer)` → `Set[str]`）
3. 匹配 regime（`regime.match(strategy.regimes, flags)`）
4. 若 regime 切换 → emit `strategy_update {type: 'regime_changed', ...}` + audit
5. 对当前 regime 的所有 enabled grids：判断触发条件 + 底仓保护 → plan actions
6. 对每个 action：调 `ord_stk(...)` → audit 关联 order_no
7. **任何评估（无论是否触发）** 写 audit row，留痕

**Why 每 tick 评估而非定时轮询**：实时性 + 0 空转。

**风险**：高频 tick + 多策略时 CPU 飙升 → 限制：单策略最多 100 tick/s 触发评估（buffer 滑动窗口自然节流）。

### 5. v1 标志 = 后端硬编码 8 种 + 前端只读

`server/services/strategy/flags.py` 暴露：
```python
FLAG_REGISTRY = {
    'ma_bullish': {'name': '均线多头', 'category': 'trend', 'compute': _detect_ma_bullish},
    'ma_bearish': {'name': '均线空头', 'category': 'trend', 'compute': _detect_ma_bearish},
    'rsi_overbought': {'name': 'RSI超买', 'category': 'oscillator', 'compute': _detect_rsi_ob},
    'rsi_oversold': {'name': 'RSI超卖', 'category': 'oscillator', 'compute': _detect_rsi_os},
    'vol_breakout': {'name': '量能突破', 'category': 'volume', 'compute': _detect_vol_breakout},
    'price_change_up': {'name': '涨幅≥1%', 'category': 'momentum', 'compute': _detect_price_up},
    'price_change_down': {'name': '跌幅≤-1%', 'category': 'momentum', 'compute': _detect_price_down},
    'macd_golden_cross': {'name': 'MACD金叉', 'category': 'trend', 'compute': _detect_macd_gc},
    'macd_death_cross': {'name': 'MACD死叉', 'category': 'trend', 'compute': _detect_macd_dc},
}
```

**Why 硬编码**：v1 阈值是经验值，开放自定义会引入调参灾难；先把流程跑通，v2 再开放阈值自定义（带预设回退）。

### 6. Schema 设计

```sql
CREATE TABLE strategy (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  stock_code VARCHAR(16) NOT NULL,
  type VARCHAR(16) NOT NULL DEFAULT 'general',  -- 'general' / 't0' — 区分普通策略 vs T0 策略
  reference_price DECIMAL(18,4) NOT NULL,  -- 创建时锁定
  status VARCHAR(16) NOT NULL DEFAULT 'active',  -- active / paused / stopped
  base_volume INTEGER NOT NULL DEFAULT 0,  -- 全局默认底仓，regime 可覆盖
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);
CREATE INDEX ix_strategy_user_status ON strategy(user_id, status);
CREATE INDEX ix_strategy_type ON strategy(type);  -- 支撑 T0 端点 JOIN 过滤

CREATE TABLE strategy_regime (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id INTEGER NOT NULL REFERENCES strategy(id) ON DELETE CASCADE,
  name VARCHAR(64) NOT NULL,  -- 例：多头趋势 / 震荡市 / 紧急清仓
  priority INTEGER NOT NULL DEFAULT 0,
  required_flags JSON NOT NULL DEFAULT '[]',  -- ["ma_bullish", "macd_golden_cross"]
  exclude_flags JSON NOT NULL DEFAULT '[]',
  base_volume INTEGER,  -- NULL=继承 strategy.base_volume
  clear_position BOOLEAN NOT NULL DEFAULT FALSE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);
CREATE INDEX ix_regime_strategy_priority ON strategy_regime(strategy_id, priority DESC);

CREATE TABLE strategy_grid (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  regime_id INTEGER NOT NULL REFERENCES strategy_regime(id) ON DELETE CASCADE,
  direction VARCHAR(8) NOT NULL,  -- 'buy' / 'sell'
  step_offset DECIMAL(18,4) NOT NULL,  -- 相对 reference_price 的偏移（正=向上，负=向下）
  trigger_price DECIMAL(18,4) NOT NULL,  -- = reference_price + step_offset（冗余）
  volume INTEGER NOT NULL,
  max_fires INTEGER,  -- NULL=不限
  fired_count INTEGER NOT NULL DEFAULT 0,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  priority INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);
CREATE INDEX ix_grid_regime ON strategy_grid(regime_id);

CREATE TABLE strategy_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id INTEGER NOT NULL REFERENCES strategy(id) ON DELETE CASCADE,
  regime_id INTEGER,
  trd_date VARCHAR(8) NOT NULL,  -- YYYYMMDD
  trigger_type VARCHAR(32) NOT NULL,  -- 'grid_buy' / 'grid_sell' / 'clear' / 'no_match' / 'regime_switch'
  flags_active JSON NOT NULL DEFAULT '[]',
  current_price DECIMAL(18,4),
  position_vol INTEGER,
  base_volume INTEGER,
  action_payload JSON,  -- {"order_type":"23", "volume":100, "price":12.34} 或 null
  order_no VARCHAR(8),
  reject_reason VARCHAR(255),  -- 拒触发原因（如：'base_floor_protected' / 'max_fires_reached'）
  created_at DATETIME NOT NULL
);
CREATE INDEX ix_audit_strategy_date ON strategy_audit(strategy_id, trd_date, created_at DESC);
```

### 7. WS 频道 `strategy_update`

payload schema：
```json
{
  "type": "regime_changed",       // or "grid_triggered" / "grid_rejected"
  "strategy_id": 12,
  "stock_code": "600519.SH",
  "regime_id": 5,
  "regime_name": "多头趋势",
  "from_regime_id": 3,
  "from_regime_name": "震荡市",
  "trigger_grid": { "direction": "buy", "step_offset": -0.5, "volume": 100, "trigger_price": 1820.0 },
  "current_price": 1819.5,
  "position_vol": 500,
  "base_volume": 100,
  "order_no": "10000023",          // 仅 grid_triggered
  "reject_reason": null,           // 仅 grid_rejected
  "ts": "2026-07-05T10:23:45.123Z"
}
```

**Why 单独频道**：策略事件量可能远高于 order/trade push，独立频道避免污染既有 5 个频道。

### 8. 灰度开关

`server/.env`：
```
STRATEGY_ENGINE_ENABLED=false   # 默认关；生产改 true 启用引擎
HQ_WS_URL=ws://localhost:8765/ws/quote
```

启动行为：
- `STRATEGY_ENGINE_ENABLED=false`：`quote_consumer` 不创建 task；`strategy.router` 注册但端点首部检查 enabled，返 503 `{code: ENGINE_DISABLED}`
- `STRATEGY_ENGINE_ENABLED=true`：`quote_consumer` 后台启动，监听连接失败重试；API 正常服务

**Why 默认 false**：v1 上线后先内部验证 1 周，再开 trader 公测。

### 9. 前端模块边界

`client/src/modules/strategy/` 与 `T0Trade.vue` 是**两个独立模块**，互不引用。共同依赖：
- `quoteStore.getLastPrice(code)` — 实时价（前端用于预览当前 regime / 显示触发倒计时）
- `holdingsStore.cachedAsset / positions` — 持仓 / 资金（前端用于显示底仓 / 可用量）
- `api/strategy.js` — REST 客户端

**StrategyTrade.vue** 不 import `t0-trade-polish` 的任何 composable（避免隐式耦合）。

### 10. 不修改 broker 协议 / RPC 客户端契约 + Strategy 是总表

`Strategy` 是**管理策略的总表**（顶层实体，user 通过 CRUD 它来管理整套策略配置）。所有该策略产生的订单 `Order.user_def = str(strategy.id)`（裸 strategy_id 作 key，无 'STRATEGY:' 前缀），作为 Order → Strategy 的**外键关联**。

策略引擎调 `ord_stk` 与 trader 手动下单**完全走同一条路径**。broker 端无需任何改动，audit 链路通过 `Order.user_def` JOIN `strategy` 表即可回溯「这单是策略 X 在 regime Y 的网格 Z 触发」。

**与现有 `user_def` 用法共存**：
- `user_def = ''` — 普通手动单（无标签）
- `user_def = 'T0'` — **手动** T0 标签（沿用 REQ-TRADE-006，**仅适用于手动 T0Trade.vue 下单**，不含策略引擎单）
- `user_def = 'CANCEL:{orig_order_no}'` — 撤单 audit row（沿用 REQ-TRADE-003 §v9）
- `user_def = str(strategy.id)` — 策略引擎单（**所有 type** 含 general / t0，新增本 change）

**T0 端点迁移**（关键）：由于 T0 策略的 `user_def = str(strategy.id)`（不再用 `'T0'`），现有 T0 端点 MUST 同步修改以 JOIN `strategy` 表：

- `GET /api/orders/t0-stats/{stock_code}?t0_only=true`
  - 旧：`WHERE Order.user_def == 'T0'`
  - 新：`JOIN strategy ON Order.user_def = CAST(strategy.id AS TEXT) WHERE strategy.type = 't0' AND strategy.stock_code = '{stock_code}'`
  - 含「T0 策略单」+「手动 T0 单」两类（前者靠 JOIN，后者保留 `user_def='T0'` 直接匹配）
- `GET /api/orders/t0-exposure?trd_date=YYYYMMDD` — 同上 JOIN 改造
- `GET /api/orders/t0-aggregate?days=30` — 同上 JOIN 改造
- `services/t0_aggregate.py::apply_user_def_filter` 入参从 `user_def='T0'` 扩展为支持 `user_def` + `strategy_type='t0'` 双条件

**关联查询范式**：
- 「策略 5 的所有订单」：`SELECT * FROM orders WHERE user_def = '5'`（user_def 已加索引 `IX_ORDERS_USER_DEF`）
- 「所有策略订单（含策略名 + type）」：`SELECT o.*, s.name, s.type FROM orders o JOIN strategy s ON o.user_def = CAST(s.id AS TEXT)`
- 「T0 策略订单」：`JOIN strategy WHERE strategy.type = 't0'`
- 「手动 T0 单」（非策略）：`WHERE user_def = 'T0'`
- 「非策略 / 非 T0 / 非撤单订单」：`WHERE user_def = '' OR (user_def NOT IN (SELECT CAST(id AS TEXT) FROM strategy) AND user_def != 'T0' AND user_def NOT LIKE 'CANCEL:%')`
- 「撤单审计」：`WHERE user_def LIKE 'CANCEL:%'`（保留前缀解析）

**Schema 变更**：
- 在 `server/models/orm.py` 给 `Order` 加索引 `Index("ix_orders_user_def", "user_def")`（与现有 `ix_orders_stock` 等平级），无 UNIQUE 约束（保持透传语义）
- 在 `server/services/strategy/models.py` 给 `Strategy` 加 `type` 字段（`'general'` / `'t0'`）+ `Index("ix_strategy_type", "type")` 索引

## Risks / Trade-offs

- **[Risk] 后端 WS 客户端断线处理**：hqserver 重启 / 网络抖动时丢 tick → 部分网格漏触发。Mitigation：重连后用最新价重算 indicator buffer（不补历史），regime 可能瞬间切换但不丢单（单子都在 broker 端）；audit log 记录「连接断开」事件。

- **[Risk] tick 风暴时 CPU 飙高**：100+ 策略 × 100 tick/s = 10000 次评估/秒。Mitigation：单策略 tick 节流（buffer 滑动只算最近 100 tick，O(n)）；指标计算全部 numpy 向量化（v1 用 Python list，v2 切 numpy）。

- **[Risk] 网格同时触发多个 action**（如 buy + sell 都达条件）：单 tick 内下单顺序不保证 → broker 端可能先卖后买导致底仓被突破。Mitigation：单 tick 内 action 队列按 direction 排序（sell 先，buy 后），单 ticker 内串行调用 `ord_stk`。

- **[Risk] 手动撤单 / broker 主动撤单 vs 策略**：broker 推送的撤单会更新 Order.status，策略引擎下次评估时 `position.vol` 已同步（走 `cachedAsset` / `positions`），自然调整。

- **[Risk] Regime 频繁切换（震荡市标志反复）**：grids 反复触发 → 手续费堆积。Mitigation：regime 切换加 cooldown（同 regime 切换间隔 ≤ 5min 内不重复切换，audit 标记 `regime_cooldown`）。

- **[Risk] user_def 字段长度限制**：`Order.user_def VARCHAR(255)`（见 `data-model/spec.md` §1.1）。`str(strategy.id)` 最大约 10 字符（int64），余 245 字符够 future 扩展（如 `f"{strategy_id}:{regime_id}"`）。

- **[Risk] 跨日持久化**：strategy_audit 表留所有当日触发，跨日清理由日初任务（`do_reconcile`）一并处理（v1 不实现跨日归档，v2 再加）。

- **[Risk] 测试隔离**：quote_consumer 需要 mock hqserver WS，pytest 集成测试成本高。Mitigation：`engine.evaluate_tick` 接受 tick dict 入参（不依赖 ws），单测直接调；quote_consumer 单测用 `websockets` 的 test server fixture。

## Migration Plan

**v1 灰度上线**：
1. 部署后端（`STRATEGY_ENGINE_ENABLED=false` 默认）→ trader 不可见，无感
2. 内部 admin 启用开关 + 跑 1 个 demo 策略（监控 1 周）
3. 验收 OK → 改 README + 加前端入口到导航栏（trader 可见）
4. v2 收集 trader 反馈：自定义阈值 / 多标的 / 回测

**回滚**：
- 单 commit revert（按 tasks.md 拆分粒度）
- 4 张表无外部消费者，drop table 即可
- `STRATEGY_ENGINE_ENABLED=false` 立即停引擎，trader 零影响

## Open Questions

- **多策略同标的冲突**：v1 限制每 (user, stock_code) 唯一 active strategy，多策略叠加下个 change
- **跨夜持仓**：策略在 15:00 收盘后停止评估，次日 9:30 重新启动（沿用 broker 交易时段）— 待补 trading-day 时段判断逻辑
- **策略暂停 vs 停止**：暂停 = 不评估但保留所有状态；停止 = 清除所有 grids fired_count？v1 用 status='paused'/'stopped' 二态，停止不重置 fired_count（手动清空按钮）
- **回测**：`audit` 表累积足够数据后可做「按时间回放」基础，但完整回测框架（带手续费、滑点）下个 change