# trading — 委托 / 成交 / 资金

## Purpose

交易员通过 Web 平台对 QMT 柜台下达买卖指令、查询状态。
**唯一数据源是 QMT 柜台**（通过 msgpacket RPC），后端不维护内存委托/成交副本。

## Requirements

### REQ-TRADE-001: 查询

- `GET /api/orders?stock_code=...` — 委托列表（走 `qry_orders`）
- `GET /api/trades?stock_code=...` — 成交列表（走 `qry_trades`）
- `GET /api/asset` — 账户资金（走 `qry_asset`）
- 响应统一 `{code: 0, msg: "", list: [...]}`；code≠0 表示 RPC 错误

### REQ-TRADE-002: 下单

- `POST /api/orders/place`
- 必传：`stock_code, order_type, volume, price, price_type`
- `order_type` 数字串：股票场景 `23=买入 24=卖出`
- `price_type` 数字：`5=最新价 11=指定价 14=对手价 44=市价 ...`
- 走 `ord_stk` RPC，等待柜台 ack，**fire-and-forget 后状态变更靠 push 推送**

### REQ-TRADE-003: 撤单

- `DELETE /api/orders/{order_id}`
- 走 `cancel_ord` RPC，`order_id` 写入请求体
- 状态变更由 push 队列异步推送（前端 WS 收到后更新 store）
- **实现约定**：`api/orders.py` 中 import 使用别名 `from rpc.client import cancel_order as rpc_cancel_order`，避免与路由函数同名递归

### REQ-TRADE-004: 鉴权

- 全部 `/api/orders` `/api/trades` `/api/asset` 路由必须登录
- `POST /orders/place` 和 `DELETE /orders/{id}` 额外要求 `trader` 或 `admin` 角色

### REQ-TRADE-005: 前端实时性

- 后端 RPC 客户端监听 `EvTrade.Test.Push` 队列
- 收到 `ord_cfm` → 路由到 WS 频道 `order_update`
- 收到 `trd_cfm` → 路由到 WS 频道 `trade_update`
- 收到资产变更 → `asset_update`（当前**未识别**，待补）

## Scenarios

### S-TRADE-001: 下一笔限价买单

Given trader 已登录，钱够  
When `POST /api/orders/place {stock_code:"600030.SH", order_type:"23", volume:100, price:12.34, price_type:11}`  
Then 柜台返回 ack（order_id 形式 `{exchange}|{seq}`）  
And 数秒后 WS 收到 `order_update` 推送（status: "48" 待报 或 "49" 已报）

### S-TRADE-002: 撤单

Given 委托 12345 状态是已报  
When `DELETE /api/orders/12345`  
Then 柜台返回 ack  
And WS `order_update` 推送 status="54" 已撤

### S-TRADE-003: 查委托（按股票过滤）

When `GET /api/orders?stock_code=600030.SH`  
Then 返回该股票的全部委托，**不包含**其他股票

## API Surface

| Method | Path | RPC | Auth |
|---|---|---|---|
| GET | `/api/orders` | `qry_orders` | login |
| POST | `/api/orders/place` | `ord_stk` | trader |
| DELETE | `/api/orders/{id}` | `cancel_ord` | trader |
| GET | `/api/trades` | `qry_mch` | login |
| GET | `/api/asset` | `qry_asset` | login |

## Known Issues (from analysis)

- 🟥 ~~`DELETE /orders/{id}` 之前只改内存假撤单~~ → **本轮已修**（走真 RPC）
- 🟥 ~~`services/trading.py` 118 行内存仓~~ → **本轮已删**
- 🟡 `asset_update` 推送功能未实现（RPC 客户端收到资产变更无路由）
- 🟡 价格类型枚举在 api 层用数字、后端 RPC 用数字、文档用文字 → 应统一映射
