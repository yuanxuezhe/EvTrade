# positioning — 持仓查询

## Purpose

展示当前账户的全部持仓，含初始持仓、今日买卖、可卖、总持仓。
**读本地 DB**（positions 表由 pos_cfm push handler + do_reconcile 写入），不直接调 RPC。

## Requirements

### REQ-POS-001: 查询全部持仓

- `GET /api/positions` 和 `GET /api/holdings`
- 读本地 `positions` 表，响应 `{code, msg, list: [Position]}`
- Position 字段：`stock_code, stock_name, last_vol, today_buy, today_sell, avl_vol, vol, cost_price`
- **market_value 不由后端计算**：前端通过 `holdings.js:liveMarketValue` 根据实时行情 × 总持仓计算
- 后端返回 `cost_price * vol` 作为成本市值代理（前端行情未到时的 fallback）

### REQ-POS-002: 鉴权

- 必须登录；`viewer/trader/admin` 全部可读

### REQ-POS-003: 数据来源

- Push 路径：柜台 `pos_cfm` → `push_handlers.handle_pos_cfm` → 按 `stock_code` 主键 UPSERT positions 表
- 对账路径：`do_reconcile` → `qry_positions` RPC → `_apply_broker_data` → 清空 + 批量重写 positions 表
- 读路径：纯读 DB，不调 RPC

## Scenarios

### S-POS-001: 正常查持仓

When `GET /api/positions`
Then 返回当前激活交易日持仓，按 `stock_code` 排序

### S-POS-002: 推送更新

Given 柜台推送 pos_cfm 消息
When `handle_pos_cfm` 收到
Then upsert positions 表对应行（不写 market_value 字段）

## API Surface

| Method | Path | 数据源 | Auth |
|---|---|---|---|
| GET | `/api/positions` | DB | login |
| GET | `/api/holdings` | DB | login |

## Known Issues (from analysis)

- 🟥 ~~`POST /api/positions/{code}/init` 内存 init 接口~~ → **已删**
- 🟡 `position_update` WS 频道 push 路由待完善
- 🟡 `market_value` 字段由前端计算，后端不存（commit `2026-06-15` 确认设计）
