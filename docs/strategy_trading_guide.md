# EvTrade 策略交易使用指南

> ## ⛔ 已下线（2026-08-10，commit `aa70dae`）
>
> 本指南描述的**网格策略 / T0 策略接口（`/api/strategy/*`）已随旧网格策略引擎删除**：REST 端点、`StrategyTrade.vue` 前端、`strategy_update` WS 频道、`STRATEGY_ENGINE_ENABLED` 配置均已移除，`strategy` / `strategy_regime` / `strategy_grid` / `strategy_audit` 表已 DROP。
>
> **现行策略形态**：**脚本策略**（前端 `ScriptDev.vue` / `ScriptTask.vue` 写 Python 脚本 + 回测 + 实盘），引擎为独立服务 `strategy_exec/`（Backtrader）。
> 参考：
> - 引擎与用户脚本接口：`openspec/specs/strategy-exec/spec.md`
> - v90 用户脚本 → Backtrader 迁移指南：[`strategy-migration-v90-to-bt.md`](./strategy-migration-v90-to-bt.md)
>
> 本文件保留为**历史记录**（T0 日内做T部分接口也已迁移/改版），不再作为操作依据。

## 目录

1. [前置准备](#1-前置准备)
2. [普通网格策略](#2-普通网格策略)
3. [T0 日内做T策略](#3-t0-日内做t策略)
4. [WebSocket 实时推送](#4-websocket-实时推送)
5. [常见问题](#5-常见问题)

---

## 1. 前置准备

### 1.1 启用策略引擎

策略引擎默认关闭，需要在 `.env` 文件中开启：

```bash
# server/.env
STRATEGY_ENGINE_ENABLED=1
```

修改后重启服务：

```bash
python scripts/evctl.py restart
```

### 1.2 确认行情数据流通

策略引擎依赖实时行情 tick 数据，确认以下链路正常：

- QMT 柜台 → RabbitMQ → hqserver（端口 8765）→ QuoteConsumer → 策略引擎
- 日志中应能看到 `[quote_consumer health] engines=N ticks_total=...` 的 30 秒心跳

### 1.3 登录获取 Token

所有策略 API 需要登录 Token，使用 OAuth2 Password Flow：

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -d "username=admin&password=admin123"
```

返回：
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": { "id": 1, "username": "admin", "role": "admin" }
}
```

后续请求在 Header 携带：`Authorization: Bearer <token>`

为方便下文，设环境变量：
```bash
TOKEN="eyJ..."
BASE="http://localhost:8000/api/strategy"
```

---

## 2. 普通网格策略

普通网格策略基于**固定价格网格线**运行：当行情价格触及 grid 的 `trigger_price` 时自动下单。适合震荡行情中的网格交易。

### 2.1 核心概念

| 概念 | 说明 |
|------|------|
| **Strategy** | 策略总表，绑定一个标的 `stock_code`，含底仓 `base_volume` |
| **Regime** | 参数集，含 required/exclude 技术标志约束 + 优先级 |
| **Grid** | 网格线，定义买入/卖出的触发价格、成交量、最大触发次数 |
| **Flag** | 技术标志，共 9 种：均线多头/空头、RSI 超买/超卖、量能突破、涨跌幅、MACD 金叉/死叉 |

### 2.2 查看支持的 Flag

```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE/flags/definitions" | python -m json.tool
```

返回 9 种技术标志：

```json
{
  "list": [
    { "code": "ma_bullish",        "name": "均线多头", "category": "trend",      "description": "MA5>MA10>MA20" },
    { "code": "ma_bearish",        "name": "均线空头", "category": "trend",      "description": "MA5<MA10<MA20" },
    { "code": "rsi_overbought",    "name": "RSI超买",  "category": "oscillator", "description": "RSI(6) ≥ 70" },
    { "code": "rsi_oversold",      "name": "RSI超卖",  "category": "oscillator", "description": "RSI(6) ≤ 30" },
    { "code": "vol_breakout",      "name": "量能突破", "category": "volume",     "description": "当根 vol ≥ 2× MA_VOL(20)" },
    { "code": "price_change_up",   "name": "涨幅≥1%",  "category": "momentum",   "description": "..." },
    { "code": "price_change_down", "name": "跌幅≤-1%", "category": "momentum",   "description": "..." },
    { "code": "macd_golden_cross", "name": "MACD金叉", "category": "trend",      "description": "..." },
    { "code": "macd_death_cross",  "name": "MACD死叉", "category": "trend",      "description": "..." }
  ]
}
```

### 2.3 创建网格策略

以下创建一个 600519.SH（贵州茅台）的网格策略，参考价 1800，底仓 200 股：

- **Regime 1**（多头趋势）：当 `ma_bullish` 激活时，在参考价下方设 3 条买入 grid，上方设 2 条卖出 grid
- **Regime 2**（超卖反弹）：当 `rsi_oversold` 激活且排除 `ma_bearish` 时，在更低价位设买入 grid

```bash
curl -s -X POST "$BASE" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
  "stock_code": "600519.SH",
  "reference_price": 1800.0,
  "base_volume": 200,
  "note": "茅台网格策略",
  "regimes": [
    {
      "name": "多头趋势",
      "priority": 10,
      "required_flags": ["ma_bullish"],
      "exclude_flags": ["rsi_overbought"],
      "grids": [
        { "direction": "buy",  "step_offset": -30.0, "trigger_price": 1770.0, "volume": 100, "max_fires": 5 },
        { "direction": "buy",  "step_offset": -60.0, "trigger_price": 1740.0, "volume": 100, "max_fires": 3 },
        { "direction": "sell", "step_offset": +20.0, "trigger_price": 1820.0, "volume": 100, "max_fires": 5 },
        { "direction": "sell", "step_offset": +50.0, "trigger_price": 1850.0, "volume": 100, "max_fires": 3 }
      ]
    },
    {
      "name": "超卖反弹",
      "priority": 5,
      "required_flags": ["rsi_oversold"],
      "exclude_flags": ["ma_bearish"],
      "grids": [
        { "direction": "buy", "step_offset": -100.0, "trigger_price": 1700.0, "volume": 200, "max_fires": 2 }
      ]
    }
  ]
}' | python -m json.tool
```

返回创建成功的策略对象，记录 `id`（如 `id: 3`）。

**关键字段说明：**

| 字段 | 说明 |
|------|------|
| `reference_price` | 参考价格，grid 的 step_offset 基于此计算 |
| `base_volume` | 底仓股数，卖出时 `position - base_volume` 为可卖数量 |
| `required_flags` | 必须全部激活才匹配此 regime（AND 逻辑） |
| `exclude_flags` | 任一激活则排除此 regime（NOT 逻辑） |
| `priority` | 优先级，数字越大越优先匹配 |
| `trigger_price` | 触发价格（buy ≤ trigger / sell ≥ trigger） |
| `max_fires` | 最大触发次数，`null` 表示不限 |

### 2.4 策略管理

**列表查询：**
```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE" | python -m json.tool
# 过滤：?status=active  / ?type=general
```

**查看详情：**
```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE/3" | python -m json.tool
```

**更新策略（暂停/恢复/停用）：**
```bash
# 暂停
curl -s -X POST "$BASE/3/control" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "pause"}'

# 恢复
curl -s -X POST "$BASE/3/control" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "resume"}'

# 停用（彻底停止）
curl -s -X POST "$BASE/3/control" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "stop"}'
```

**查看审计日志：**
```bash
# 查看 20260728 当天的策略触发记录
curl -sH "Authorization: Bearer $TOKEN" "$BASE/3/audit?trd_date=20260728" | python -m json.tool
```

**删除策略：**
```bash
curl -s -X DELETE "$BASE/3" \
  -H "Authorization: Bearer $TOKEN"
```

### 2.5 运行流程

```
行情 tick → QuoteConsumer → StrategyEngine.evaluate_tick()
    |
    ├── 1. tick 入 buffer（滚动 100 帧）
    ├── 2. 检测 9 种技术标志
    ├── 3. 匹配 Regime（required/exclude + 优先级）
    ├── 4. 冷却检查（5 分钟内不重复切换 regime）
    ├── 5. 评估 Grid（buy: price ≤ trigger / sell: price ≥ trigger）
    ├── 6. 底仓保护（sell 时不穿透 base_volume）
    └── 7. 触发 → INSERT Order → ord_stk RPC → broker 下单
```

---

## 3. T0 日内做T策略

T0 策略基于日内分时行情信号运行，核心围绕 **VWAP量价背离**、**开盘冲跌**、**5分钟布林线触轨** 三大信号模型。支持**测试/实盘**双模式。

### 3.1 核心概念

| 概念 | 说明 |
|------|------|
| **测试模式** (`test_mode=true`) | 仅展示信号，不实际下单。适合验证策略效果 |
| **实盘模式** (`test_mode=false`) | 信号满足条件时自动通过 broker 下单 |
| **正T** | 先买后卖（低吸 → 冲高卖出） |
| **倒T** | 先卖后买（高抛 → 急跌买回） |

### 3.2 三大信号模型

**模型 1 — VWAP 乖离率回归（胜率最高）**

| 信号 | 触发条件 |
|------|----------|
| 正T买入 | 股价偏离 VWAP 向下超过 1.5%~2.5%，且 5 分钟 K 线出现下影线或止跌阳线 |
| 倒T卖出 | 股价偏离 VWAP 向上超过 2%~3%，且成交量不能持续放大 |
| 平仓 | 股价回归至 VWAP 附近（偏离 < 0.8%） |

**模型 2 — 开盘30分钟冲高/急跌**

| 信号 | 触发条件 |
|------|----------|
| 倒T卖出 | 开盘 10 分钟内冲高超过 3%，09:35~09:45 区间量能未跟进 |
| 正T买入 | 开盘快速急跌超过 2.5%，无异常恐慌巨量 |

**模型 3 — 5分钟布林线触轨**

| 信号 | 触发条件 |
|------|----------|
| 正T买入 | 股价跌破 5 分钟布林下轨 + RSI(6) < 20 |
| 倒T卖出 | 股价突破 5 分钟布林上轨 + RSI(6) > 80 |

### 3.3 风控规则（全部可配）

| 规则 | 默认值 | 说明 |
|------|--------|------|
| 单笔止损 | 1.5% | 做T仓位亏损达此幅度强制平仓 |
| 时间截断 | 14:30 | 此前必须全部平仓，不留尾仓 |
| 日限频次 | 2 次/标 | 防止过度交易 |
| 信号冷却 | 120 秒 | 两次信号最小间隔 |
| 底仓保护 | 策略 `base_volume` | 做T卖出不可穿透底仓 |

### 3.4 创建 T0 策略（测试模式）

以下创建 600519.SH 的 T0 策略，**test_mode=true**（仅信号，不下单）：

```bash
curl -s -X POST "$BASE/t0" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
  "stock_code": "600519.SH",
  "reference_price": 1800.0,
  "base_volume": 500,
  "note": "茅台T0策略",
  "test_mode": true,
  "models_enabled": ["vwap", "opening", "bollinger"],
  "signal_volume": 200,
  "signal_cooldown": 120,
  "vwap_params": {
    "buy_deviation_low": 0.015,
    "buy_deviation_high": 0.025,
    "sell_deviation_low": 0.02,
    "sell_deviation_high": 0.03,
    "close_deviation": 0.008,
    "require_kline_signal": true
  },
  "opening_params": {
    "surge_threshold": 0.03,
    "drop_threshold": 0.025,
    "sell_window_start": 575,
    "sell_window_end": 585,
    "opening_period_minutes": 30
  },
  "bollinger_params": {
    "period": 20,
    "std_mult": 2.0,
    "rsi_period": 6,
    "rsi_oversold": 20.0,
    "rsi_overbought": 80.0
  },
  "risk_params": {
    "stop_loss_pct": 0.015,
    "time_cutoff": 870,
    "max_operations_per_day": 2
  }
}' | python -m json.tool
```

**参数说明：**

| 参数 | 说明 | 典型取值 |
|------|------|----------|
| `base_volume` | 底仓股数，做T不可卖超此数量 | 持仓的 50%~70% |
| `signal_volume` | 单次信号的默认交易股数 | 100/200/500（整手） |
| `signal_cooldown` | 信号冷却秒数 | 60~300 |
| `buy_deviation_low` | VWAP 买入偏离下限 | 高波动标的 0.02~0.03 |
| `sell_deviation_low` | VWAP 卖出偏离下限 | 高波动标的 0.025~0.04 |
| `require_kline_signal` | VWAP 信号是否需 K 线确认 | 低波动标的可设为 false |
| `time_cutoff` | 强制平仓时间（分钟数，870=14:30） | 840~870 |

### 3.5 策略管理

**列表（仅 T0 策略）：**
```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE/t0" | python -m json.tool
```

**查看详情：**
```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE/t0/4" | python -m json.tool
```

**切换为实盘模式：**
```bash
curl -s -X PUT "$BASE/t0/4" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"test_mode": false}' | python -m json.tool
```

**调整参数（热更新，无需重启）：**
```bash
# 调大 VWAP 偏离阈值（适合高波动标的）
curl -s -X PUT "$BASE/t0/4" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "vwap_params": {
      "buy_deviation_low": 0.02,
      "sell_deviation_low": 0.025
    },
    "risk_params": {
      "stop_loss_pct": 0.02,
      "max_operations_per_day": 3
    }
  }' | python -m json.tool
```

**暂停/恢复/停用：**
```bash
curl -s -X POST "$BASE/t0/4/control" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "pause"}'
# action: pause / resume / stop
```

**查看当日信号历史：**
```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE/t0/4/signals?trd_date=20260728&limit=50" \
  | python -m json.tool
```

返回示例：
```json
[
  {
    "strategy_id": 4,
    "signal_type": "vwap_buy",
    "model": "vwap",
    "direction": "buy",
    "price": 1765.0,
    "volume": 200,
    "reason": "VWAP偏离 -2.10%，K线止跌",
    "strength": 0.8,
    "order_no": null,
    "reject_reason": "test_mode",
    "timestamp": "2026-07-28T09:42:15"
  }
]
```

**查看当前敞口：**
```bash
curl -sH "Authorization: Bearer $TOKEN" "$BASE/t0/4/positions" | python -m json.tool
```

```json
{
  "strategy_id": 4,
  "stock_code": "600519.SH",
  "test_mode": true,
  "operations_today": 1,
  "open_positions": []
}
```

**删除：**
```bash
curl -s -X DELETE "$BASE/t0/4" \
  -H "Authorization: Bearer $TOKEN"
```

### 3.6 从测试到实盘的建议流程

1. **Week 1 — 测试观察**：`test_mode=true`，观察 3~5 个交易日，查看信号历史
2. **参数调优**：根据信号准确率，调整偏离阈值、布林周期、RSI 阈值
3. **小量实盘**：`test_mode=false` + `signal_volume=100`（最小手），实盘验证滑点和成交率
4. **逐步放量**：确认稳定后，逐步调大 `signal_volume`

---

## 4. WebSocket 实时推送

连接后端 WebSocket 可实时接收策略信号推送：

```
ws://localhost:8000/ws?token=<jwt_token>
```

### 4.1 策略推送频道

订阅后接收 `strategy_update`（普通策略）和 `t0_strategy_update`（T0 策略）频道消息。

**T0 信号推送示例：**
```json
{
  "type": "t0_signal",
  "strategy_id": 4,
  "stock_code": "600519.SH",
  "current_price": 1765.0,
  "vwap": 1802.3,
  "bb_upper": 1835.2,
  "bb_middle": 1802.3,
  "bb_lower": 1769.4,
  "current_deviation": -0.0207,
  "signals": [
    {
      "signal_type": "vwap_buy",
      "model": "vwap",
      "direction": "buy",
      "price": 1765.0,
      "volume": 200,
      "reason": "VWAP偏离 -2.07%，K线止跌",
      "strength": 0.8
    }
  ],
  "actions": [...],
  "open_positions": [...],
  "order_nos": [],
  "ts": 1751058135.0
}
```

### 4.2 行情推送

行情由 hqserver 独立推送（`ws://localhost:8765`），不包含策略信号。策略信号统一走后端 WebSocket。

---

## 5. 常见问题

### Q1: 策略创建了但没有触发信号

1. 确认 `STRATEGY_ENGINE_ENABLED=1` 且已重启
2. 确认标的有行情 tick 流入（查看日志 `[quote_consumer health]`）
3. 普通策略：确认当前行情触发了 regime 的 `required_flags`
4. T0 策略：确认 `models_enabled` 包含目标模型，偏离阈值设置合理
5. T0 策略：确认当前持仓 ≥ `base_volume + signal_volume`（否则无可做T数量）

### Q2: 信号产生了但没下单

1. T0 策略：检查 `test_mode` 是否为 `true`（测试模式不下单）
2. 检查风控：是否已达日限频次、是否超过 14:30 时间截断
3. 检查底仓保护：`position - base_volume ≤ 0` 时无法卖出
4. 检查 RPC 连通性：日志中是否有 `ord_stk failed`

### Q3: 如何调整信号敏感度

- **更敏感（更多信号）**：调低 `buy_deviation_low` / `sell_deviation_low`；调低 `rsi_oversold` / 调高 `rsi_overbought`
- **更保守（更少信号）**：调高偏离阈值；设 `require_kline_signal=true`；调大 `signal_cooldown`

### Q4: 一个标的能否同时运行普通策略和 T0 策略

可以。`type="general"` 和 `type="t0"` 是独立的引擎实例，互不干扰。但需注意：
- 两个策略产生的订单会叠加，注意控制总仓位
- 普通策略的 `base_volume` 和 T0 策略的 `base_volume` 需协调设置

### Q5: T0 策略的 VWAP 如何计算

VWAP = Σ(成交价 × 成交量) / Σ(成交量)，自开盘以来全天累加。系统采用增量计算，无需每次遍历全天 tick。每个交易日开盘自动重置。

### Q6: 14:30 时间截断后还会收到信号吗

14:30 后：
- **不接受新信号**（不会开新仓）
- **强制平仓**所有 open positions
- 14:30 后仍可在信号历史中看到 `risk_stop_loss` / `close_position` 类型的平仓记录

### Q7: 日志查看

```bash
# 后端服务日志
tail -f .logs/backend.log | grep -i "t0\|strategy"

# 行情服务日志
tail -f .logs/hqserver.log
```

---

## 附录：API 速查表

### 普通策略

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategy` | 策略列表 |
| POST | `/api/strategy` | 创建策略 |
| GET | `/api/strategy/{id}` | 详情 |
| PUT | `/api/strategy/{id}` | 更新 |
| DELETE | `/api/strategy/{id}` | 删除 |
| POST | `/api/strategy/{id}/control` | pause/resume/stop |
| GET | `/api/strategy/{id}/audit?trd_date=...` | 审计日志 |
| GET | `/api/strategy/flags/definitions` | 技术标志列表 |

### T0 策略

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategy/t0` | T0 策略列表 |
| POST | `/api/strategy/t0` | 创建 T0 策略 |
| GET | `/api/strategy/t0/{id}` | 详情 + 参数 |
| PUT | `/api/strategy/t0/{id}` | 更新参数（热更新） |
| DELETE | `/api/strategy/t0/{id}` | 删除 |
| POST | `/api/strategy/t0/{id}/control` | pause/resume/stop |
| GET | `/api/strategy/t0/{id}/signals?trd_date=...&limit=100` | 信号历史 |
| GET | `/api/strategy/t0/{id}/positions` | 当前 T0 敞口 |
