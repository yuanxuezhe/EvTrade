# positioning — 持仓查询

> 📖 **数据结构**详见 [`data-model/spec.md`](../data-model/spec.md) §1（positions）

## Purpose

展示当前账户的全部持仓，含初始持仓、今日买卖、可卖、总持仓。
**读本地 DB**（positions 表由 pos_cfm push handler + do_reconcile 写入），不直接调 RPC。

## Requirements

### REQ-POS-001: 查询全部持仓

- `GET /api/positions` 和 `GET /api/holdings`
- 读本地 `positions` 表，响应 `{code, msg, list: [Position]}`
- **Position 字段语义（v5 schema-refactor，**详细见 `data-model/spec.md` 第 3 节**）**：
  - `stock_code` — PK
  - `stock_name` — 股票名
  - `last_vol` — **期初持仓**（由 `do_reconcile` 设置；pos_cfm 不写）
  - `today_buy` / `today_sell` — 今日买卖累计（**只由 do_reconcile 设置**）
  - `avl_vol` — **可用**持仓
  - `vol` — **总持仓**（pos_cfm 写入；缺字段时兜底为 `avl_vol`，见 REQ-POS-004）
  - `cost_price` — 成本价
- **market_value 不由后端计算**：前端通过 `holdings.js:liveMarketValue` 根据实时行情 × 总持仓计算
- 后端返回 `cost_price * vol` 作为成本市值代理（前端行情未到时的 fallback）

### REQ-POS-002: 鉴权

- 必须登录；`viewer/trader/admin` 全部可读

### REQ-POS-003: 数据来源

- Push 路径：柜台 `pos_cfm` → `push_handlers.handle_pos_cfm` → 按 `stock_code` 主键 UPSERT positions 表
  - 字段映射：`row.volume → pos.vol`（**缺字段时兜底 `avl_vol`，见 REQ-POS-004**）、`row.available → pos.avl_vol`、`row.cost_price → pos.cost_price`
  - **不写** `last_vol` / `today_buy` / `today_sell`（注释："由对账时设置"）
  - **不写** `market_value`（前端实时算）
- 对账路径：`do_reconcile` → `qry_positions` RPC → `_apply_broker_data` → 清空 + 批量重写 positions 表
  - **对账时才写** `last_vol` / `today_buy` / `today_sell`
- 读路径：纯读 DB，不调 RPC

### REQ-POS-004: pos_cfm vol 字段兜底（2026-06-16 立）

- pos_cfm 推送行可能不送 `volume` 字段（只送 `available`）；若 `row.volume` 缺/为 0 而 `row.available > 0`，**vol 兜底为 avl_vol**
- 实现位置：`server/services/push_handlers.py:handle_pos_cfm`
- 测试用例：pos_cfm 推送 `{stock_code:"X", available:100}` 后 `positions.vol == 100`

## Scenarios

### S-POS-001: 正常查持仓

When `GET /api/positions`
Then 返回当前激活交易日持仓，按 `stock_code` 排序
And `Position.vol` 是非负整数（pos_cfm 兜底后一定有值；只有持仓真的为 0 才是 0）

### S-POS-002: 推送更新（vol 字段缺失）

Given 柜台推送 pos_cfm 行 `{stock_code:"X", available:100, cost_price:12.5}`（**不送 volume**）
When `handle_pos_cfm` 收到
Then upsert positions 表对应行，`vol = 100`（兜底自 avl_vol）
And `last_vol / today_buy / today_sell` 保持不变（只对账写）

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
