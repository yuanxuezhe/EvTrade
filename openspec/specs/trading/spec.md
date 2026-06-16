# trading — 委托 / 成交 / 资金

> 📖 **数据结构**详见 [`data-model/spec.md`](../data-model/spec.md) §1（orders / trades / assets）

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
- **v5 幂等 / 路由定位**：
  - `client_order_id` 客户端幂等号（同 cid 二次提交返原单）
  - `order_no` 服务端本地生成 8 位序号（保证当日 + 全局唯一）
  - 下单时把 `order_no` 透传到柜台 RPC 的 `remark` 字段（柜台透传，pushed-back 时带回）
  - 委托表复合主键 `(trd_date, order_no)`；`order_id` 改为可空列，由 ord_cfm 推送时单条 UPDATE 写入（v6）
- **`OrderOut.status` 语义（v6，本地推断）**：
  - 委托表 `status` 字段 = **后端本地推断的委托状态**（48/49/50/51/52/53/54/55/56）
  - 推断函数：`_infer_order_status(order, broker_status=None)`（`server/services/push_handlers.py`）
  - 规则：累计成交 + broker 推的撤单类信号 (52/53/54) 推断 49/50/51/53/56
  - 终态 (51/52/53/54/55/56) 一旦写入不再被 trd_cfm 覆盖
  - **前端必须镜像同一函数**：`client/src/utils/format.js` 提供 `inferOrderStatus(order, brokerStatus?)`，见 `frontend/spec.md` REQ-FE-006
  - **前端不再信任 broker 推的 status 字段**（broker 状态码 vs 本地推断码不完全相同：例如 broker 55=部成 → 本地 50=部成）
- **v7 schema 调整**：
  - `Order` 表删除 `client_order_id` 字段（不下发，幂等不再靠 DB UNIQUE 约束）
  - `Order` 表删除 `uq_orders_client_trd` / `uq_orders_broker_id` 约束（order_id 下单时为空，broker 约束不可靠）
  - `Order` 表新增 `user_def` 字段（`String(255)`，默认空字符串）记录外部自定义信息（前端幂等号 / 备注）
  - `Trade` 表删除 `order_id` 字段（broker 号在 trd_cfm 到达时可能尚未到达）
  - `Trade` 表新增 `order_no` 字段并入 PK（PK = `(trd_date, order_no, trade_id)`），关联键更稳定
  - 下单 API `POST /api/orders/place` 接受可选 `user_def` 字段透传（无业务约束，仅落库）
  - 下单幂等改由 `order_no` 单调递增保证（同 ord_stk RPC 第二次调用方会被 broker 拒绝）

### REQ-TRADE-003: 撤单

- `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD`
- **v6 BREAKING**：URL 参数从 `order_id` 改为 `order_no`（本地 8 位序号）；后端按 `(trd_date, order_no)` 定位 Order
- 内部用查到的 `order.order_id` 调 `rpc.cancel_ord`；`order_id` 尚未到达时返 `409 BROKER_NOT_READY`
- 走 `cancel_ord` RPC，**不本地改 status**（由 ord_cfm push 异步回写）
- **前端约定**：Trade.vue 撤单按钮 → `orderStore.cancelOrder(orderNo, trdDate)` → `api.cancelOrder(orderNo, trdDate)` → `DELETE /api/orders/${orderNo}?trd_date=${trdDate}`
- **实现约定**：`api/orders.py` 中 import 使用别名 `from rpc.client import cancel_order as rpc_cancel_order`，避免与路由函数同名递归

### REQ-TRADE-004: 鉴权

- 全部 `/api/orders` `/api/trades` `/api/asset` 路由必须登录
- `POST /orders/place` 和 `DELETE /orders/{no}` 额外要求 `trader` 或 `admin` 角色

### REQ-TRADE-005: 前端实时性

- 后端 RPC 客户端监听 `EvTrade.Test.Push` 队列
- 收到 `ord_cfm` → 路由到 WS 频道 `order_update`，**status 字段是后端本地推断结果**，前端直接用
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
- 🟥 ~~撤单 URL 用 order_id~~ → **v6 已改用 order_no**，但前端 Trade.vue 还在传 order_id（参见 change `2026-06-16-trade-page-show-order-no-and-cancel`）
- 🟡 前端 `order.js` `cancelOrder` 硬编码 `order.status = '54'`（与后端本地推断不一致）→ 参见 change `2026-06-16-frontend-infer-order-status`
- 🟡 前端 Trade.vue / Orders.vue 状态码分组用了 broker 原始码（55=已成等）而不是后端本地推断码（56=已成）→ 同上 change
- 🟡 `asset_update` 推送功能未实现（RPC 客户端收到资产变更无路由）
- 🟡 价格类型枚举在 api 层用数字、后端 RPC 用数字、文档用文字 → 应统一映射
