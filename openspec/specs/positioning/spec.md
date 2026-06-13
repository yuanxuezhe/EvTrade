# positioning — 持仓查询

## Purpose

展示当前账户的全部持仓，含初始持仓、今日买卖、可卖、总持仓。
**唯一数据源是 QMT 柜台**（`qry_pos` RPC）。

## Requirements

### REQ-POS-001: 查询全部持仓

- `GET /api/positions`
- 走 `qry_pos` RPC，响应 `{code, msg, list: [Position]}`
- Position 字段：`stock_code, stock_name, initial_position, today_buy, today_sell, available, total`

### REQ-POS-002: 鉴权

- 必须登录；`viewer/trader/admin` 全部可读

## Scenarios

### S-POS-001: 正常查持仓

When `GET /api/positions`  
Then 返回当前所有持仓，按 `stock_code` 排序

### S-POS-002: 柜台断连

Given 柜台 RPC 客户端未连接  
When `GET /api/positions`  
Then 返回 `{code: -1, msg: "<error>", list: []}`，前端 axios 拦截器弹错误 toast

## API Surface

| Method | Path | RPC | Auth |
|---|---|---|---|
| GET | `/api/positions` | `qry_pos` | login |

## Known Issues (from analysis)

- 🟥 ~~`POST /api/positions/{code}/init` 内存 init 接口~~ → **本轮已删**（柜台自动维护 initial_position）
- 🟡 `position_update` WS 频道当前**未路由**（RPC 客户端收到持仓变更无处理）
