# positioning — 持仓查询

> 📖 **数据结构**详见 [`data-model/spec.md`](../data-model/spec.md) §1（positions）

## Purpose

展示当前账户的全部持仓，含初始持仓、今日买卖、可卖、总持仓。
**读本地 DB**（positions 表由 pos_cfm push handler + do_reconcile 写入），不直接调 RPC。

## Requirements

### REQ-POS-001: 查询全部持仓

- `GET /api/positions` 和 `GET /api/holdings`
- 读本地 `positions` 表，响应 `{code, msg, list: [Position]}`
- **Position 字段语义（v12 schema，**详细见 `data-model/spec.md` 第 3 节**）**：
  - `stock_code` — PK
  - `stock_name` — 股票名
  - `last_vol` — **期初持仓**（**仅** `do_reconcile` 写入；`today_buy`/`today_sell` 已删除）
  - `avl_vol` — **可用**持仓（`do_reconcile` 写入 + `manual` 调平）
  - `vol` — **总持仓**（`do_reconcile` 写入 + `trd_cfm` push 增量；缺字段时兜底为 `avl_vol`，见 REQ-POS-004）
  - `cost_price` — 成本价（仅 `do_reconcile` 写入）
  - `synced_at` / `synced_from` — 同步时间和来源
- **market_value 不由后端计算**：前端通过 `holdings.js:liveMarketValue` 根据实时行情 × 总持仓计算
- 后端返回 `cost_price * vol` 作为成本市值代理（前端行情未到时的 fallback）
- **当日买卖累计**（"今日净变动"等展示）改由 `Trade` 表 `order_type` 聚合替代，不依赖 `Position` 字段

### REQ-POS-002: 鉴权

- 必须登录；`viewer/trader/admin` 全部可读

### REQ-POS-003: 数据来源

- Push 路径：xtquant broker 不发 `pos_cfm`，**本路径在 consolidate-position-data-flow 已被删除**；v12 仅保留 `trd_cfm` → `Position.vol` 增量路径（intra-day 实时响应成交回报，详见 `push/spec.md` REQ-PUSH-031）
  - `trd_cfm` 推 `order_type='23'`（买）→ `Position.vol += volume`
  - `trd_cfm` 推 `order_type='24'`（卖）→ `Position.vol -= volume`
  - 不动 `last_vol` / `avl_vol` / `cost_price`（由 day-init reconcile 兜底）
- 对账路径：`do_reconcile` → `qry_positions` RPC → `_apply_broker_data` → 清空 + 批量重写 positions 表
  - **对账时全表覆盖** `last_vol` / `avl_vol` / `vol` / `cost_price`（`sync_from = 'rpc_full'`）
  - **v12 行为变化**：do_reconcile 不再写入 `today_buy` / `today_sell`（字段已删）
- Manual 调平路径（v12 新增）：`PUT /api/positions/{stock_code}/adjust`（admin 鉴权）
  - 原子 `vol` 和/或 `avl_vol` 加减
  - 调平后 `sync_from = 'manual'`；下次 do_reconcile 自动覆盖回 `rpc_full`
- 读路径：纯读 DB，不调 RPC

### REQ-POS-004: pos_cfm vol 字段兜底（2026-06-16 立，consolidate-position-data-flow 阶段已废）

- pos_cfm 推送行可能不送 `volume` 字段（只送 `available`）；若 `row.volume` 缺/为 0 而 `row.available > 0`，**vol 兜底为 avl_vol**
- 实现位置：`server/services/push_handlers.py:handle_pos_cfm`
- 测试用例：pos_cfm 推送 `{stock_code:"X", available:100}` 后 `positions.vol == 100`
- **v12 注**：xtquant broker 不发 `pos_cfm`，本路径已被 trd_cfm 增量 + day-init reconcile 双路径取代；保留作为历史注释


### Requirement: 持仓查询响应字段（v12）

`GET /api/positions` 响应字段 MUST 不再含 `today_buy` / `today_sell`。前端不再消费这俩字段。

#### Scenario: GET /api/positions 响应 schema 变化

- **WHEN** 实施本 change
- **THEN** `PositionOut` Pydantic schema 不再有 `today_buy` / `today_sell`
- **AND** 前端 `useHoldingsStore().positions` 数组元素不含这俩字段
- **AND** `client/src/stores/holdings_market.js:createMarketComputeds` 不会去读这俩字段（应当 0 引用）

#### Scenario: 前端缓存表头无 today_buy / today_sell 列

- **WHEN** admin 打开 `/admin/cache/positions`
- **THEN** `CachePositions.vue` 表格列定义不含 `today_buy` / `today_sell`

### Requirement: 持仓数据来源（v12 简化）

`Position` 数据的写入来源 MUST 简化为两条路径：`do_reconcile` 全表覆盖（broker 权威），`trd_cfm` push handler 盘中增量 `vol`（实时响应成交回报）。**不再**有"pos_cfm 写入路径"（broker 不发 pos_cfm）、**不再**有"today_buy/sell 写入路径"（字段已删）。

#### Scenario: 写入路径 2 条

- **WHEN** `Position` 行被改动
- **THEN** 写入方要么是 `do_reconcile`（开盘基准）、要么是 `_update_position_vol`（`trd_cfm` handler 内调）
- **AND** `Position.last_vol` / `Position.cost_price` 仅由 `do_reconcile` 写
- **AND** `Position.vol` 由 `do_reconcile` 写或被 `trd_cfm` 累加

### Requirement: 持仓调平客户端入口（v12）

前端 MUST 通过 `api.adjustPosition(stockCode, deltaVol, deltaAvlVol)` 调用调平，详见 `asset-position-adjust/spec.md`。UI 入口位置：`/admin/cache/positions` 表格行操作列加"调平"按钮。

#### Scenario: admin 调平 Position

- **WHEN** admin 在 `/admin/cache/positions` 点击某行"调平"按钮
- **THEN** 弹出输入框 `delta_vol` / `delta_avl_vol` / `reason`（reason 仅入 log）
- **AND** 提交时调用 `api.adjustPosition(stockCode, deltaVol, deltaAvlVol)`
- **AND** 成功后在表格中即时反映（前端 watcher 触发）—— 不依赖 re-fetch

## Scenarios

### S-POS-001: 正常查持仓

When `GET /api/positions`
Then 返回当前激活交易日持仓，按 `stock_code` 排序
And `Position.vol` 是非负整数（pos_cfm 兜底后一定有值；只有持仓真的为 0 才是 0）

### S-POS-002: 推送更新（vol 字段缺失）

Given 柜台推送 pos_cfm 行 `{stock_code:"X", available:100, cost_price:12.5}`（**不送 volume**）
When `handle_pos_cfm` 收到
Then upsert positions 表对应行，`vol = 100`（兜底自 avl_vol）
And `last_vol / cost_price` 保持不变（仅 do_reconcile 写）

### S-POS-003: 推送更新（完整字段）

Given 柜台推送 pos_cfm 行 `{stock_code:"X", volume:200, available:150, cost_price:12.5}`
When `handle_pos_cfm` 收到
Then `vol = 200`（不兜底），`avl_vol = 150`

## API Surface

| Method | Path | 数据源 | Auth |
|---|---|---|---|
| GET | `/api/positions` | DB | login |
| GET | `/api/holdings` | DB | login |

## Known Issues (from analysis)

- 🟥 ~~`POST /api/positions/{code}/init` 内存 init 接口~~ → **已删**
- 🟥 ~~pos_cfm vol 字段缺失时显示 0~~ → **本轮已修**（change `2026-06-16-fix-position-vol-display`，vol 兜底 avl_vol）
- 🟡 `position_update` WS 频道 push 路由待完善
- 🟡 `market_value` 字段由前端计算，后端不存（commit `2026-06-15` 确认设计）
