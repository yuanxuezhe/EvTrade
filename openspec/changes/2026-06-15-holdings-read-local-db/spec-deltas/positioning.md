# positioning — Holdings reads local DB delta

> This delta aligns positioning spec with v4 「**本地 DB 是持仓展示源**」contract.
> The current spec.md was written before v4 persistence refactor and
> still claims `qry_pos` is the data source — this delta updates it.
> Merged into `specs/positioning/spec.md` upon approval.

## MODIFIED Requirements

### REQ-POS-001 (was): 查询全部持仓（走 qry_pos RPC）
### REQ-POS-001 (now): 持仓数据源 = 本地 positions 表

- **`GET /api/positions`** — 读本地 `positions` 表，纯 DB SELECT
- **`GET /api/holdings`** — 读本地 `positions` 表，**6 字段精简版**
- 两个端点查询同一张表，仅响应字段不同
- 写入路径：pos_cfm push handler / do_reconcile → positions 表
- 调 `qry_positions` RPC 的场景**仅剩日初对账**（`do_reconcile` 入口）

### Position 完整字段（13）

`id, TRD_DATE, stock_code, stock_name, initial_position, today_buy, today_sell, available, total, cost, market_value, synced_at, synced_from`

### HoldingItem 精简字段（6）

`stock_code, initial_position, total, available, cost, market_value`

字段映射（旧 holdings RPC 6 字段 → 新 holdings DB 6 字段）：

| 旧 RPC | 新 DB | 语义 |
|---|---|---|
| `last_vol` | `initial_position` | 昨收持仓 |
| `volume` | `total` | 当前总持仓 |
| `available` | `available` | 可卖 |
| `cost` | `cost` | 成本 |
| `market_value` | `market_value` | 市值 |
| `stock_code` | `stock_code` | 代码 |

### REQ-POS-001.1 屏障

- `GET /api/positions` — 无屏障（前端 v4 已用，可读 trading_day 任意日）
- `GET /api/holdings` — **加** trading_day 屏障：未激活日返 503 + `TRADING_DAY_NOT_INIT`
  - 原因：前端 holdings store bootstrap 失败应主动告知用户，与 `orders` 端点行为一致

### REQ-POS-001.2 查询参数

- `stock_code: Optional[str]` — 按代码过滤
- `trading_day: Optional[str]` — 默认 = 激活日（`resolve_default_trd_date`）
- 返回按 `stock_code` 排序

### REQ-POS-002 (unchanged): 鉴权

- 必须登录；`viewer/trader/admin` 全部可读

## REMOVED Requirements

### REQ-POS-001 旧 RPC 行为

- ❌ 走 `qry_pos` RPC（已迁移到本地 DB）
- ❌ 返回 `code=-1` 表 RPC 失败（现在永远 `code=0`）
- ❌ `POST /api/positions/{code}/init` 内存 init 接口（v4 已删）

## ADDED Scenarios

### S-POS-003: 冷启动 holdings 空

Given 冷启动无任何对账  
When `GET /api/holdings`  
Then 返 `code=0` + 空 list（DB 无数据，不是错误）

### S-POS-004: 日初未激活

Given 未调 `/api/admin/trading-day/init`  
When `GET /api/holdings`  
Then 返 503 + `code=TRADING_DAY_NOT_INIT`

### S-POS-005: 字段映射

Given DB 行 `Position(initial_position=100, total=200, ...)`  
When `GET /api/holdings`  
Then 返 `{stock_code, initial_position: 100, total: 200, available, cost, market_value}`  
And **不**返 `last_vol` / `volume`

## Known Issues (carried over)

- 🟡 `position_update` WS 频道当前**未路由**（RPC 客户端收到持仓变更无处理）
  — v4 已知，v6 处理
- 🟡 Position 表无 `user_id` 字段（v4 已知，按 stock_code 聚合）
- 🟢 两个端点（positions/holdings）查询同一表，**字段重复**是历史包袱，v6 合并
