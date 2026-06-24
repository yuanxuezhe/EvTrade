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
- **`OrderOut.status` 语义（v6，本地推断；v8 改 `cancelled_volume` 主轴）**：
  - 委托表 `status` 字段 = **后端本地推断的委托状态**（48/49/50/51/52/53/54/55/56）
  - 推断函数：`_infer_order_status(order, broker_status=None)`（`server/services/push_handlers.py`）
  - **v8 规则改**：以 `cancelled_volume` 主轴
    - `cancelled_volume >= volume` → 53（已撤）
    - `cancelled_volume > 0 && traded_volume > 0` → 56（部成部撤）
    - `cancelled_volume > 0`（无成交）→ 53
    - `broker_status in (52,53,54)` 兼容老 broker 协议（无 `cancelled_volume` 字段）
    - 累计推断：`traded_volume` 决定 49/50/51
  - 终态 (51/52/53/54/55/56) 一旦写入不再被 trd_cfm 覆盖
  - **前端必须镜像同一函数**：`client/src/utils/format.js` 提供 `inferOrderStatus(order, brokerStatus?)`，见 `frontend/spec.md` REQ-FE-006
  - **前端不再信任 broker 推的 status 字段**（broker 状态码 vs 本地推断码不完全相同：例如 broker 55=部成 → 本地 50=部成）
  - `OrderOut` v8 增 `cancelled_volume` 字段（默认 0），由 `handle_ord_cfm` 累加 broker 推送的撤单量
- **v7 schema 调整**：
  - `Order` 表删除 `client_order_id` 字段（不下发，幂等不再靠 DB UNIQUE 约束）
  - `Order` 表删除 `uq_orders_client_trd` / `uq_orders_broker_id` 约束（order_id 下单时为空，broker 约束不可靠）
  - `Order` 表新增 `user_def` 字段（`String(255)`，默认空字符串）记录外部自定义信息（前端幂等号 / 备注）
  - `Trade` 表删除 `order_id` 字段（broker 号在 trd_cfm 到达时可能尚未到达）
  - `Trade` 表新增 `order_no` 字段并入 PK（PK = `(trd_date, order_no, trade_id)`），关联键更稳定
  - 下单 API `POST /api/orders/place` 接受可选 `user_def` 字段透传（无业务约束，仅落库）
  - 下单幂等改由 `order_no` 单调递增保证（同 ord_stk RPC 第二次调用方会被 broker 拒绝）

### REQ-TRADE-003: 撤单（v9 重写：本地代理撤单留痕）

- `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD`
- **v6 BREAKING**：URL 参数从 `order_id` 改为 `order_no`（本地 8 位序号）；后端按 `(trd_date, order_no)` 定位 Order
- **v9 BREAKING**：DELETE 端点**立即 INSERT 一条 cancel-row**（`order_flag=1`），用于本地撤单审计；broker 不会推这个 row（broker `ord_cfm` 的 `remark` 永远是**原委托**的 `order_no`，不会回带 cancel-row 的 `order_no`）
- **5 步流程**：
  1. **Pre-checks**：原委托 `status` 不在 `{48,49,50}` → 返 `{code: NO_CANCELABLE}`，**不插行**；`order_id` 缺失 → 返 `{code: NO_ORDER_ID, http=409}`，**不插行**
  2. **INSERT cancel-row**（commit 立即落库，避免 RPC 异常时孤儿）：`order_no = next_order_no(db)`；`user_def = "CANCEL:{orig_order_no}"`；`stock_code/order_type/price_type/price` 镜像；`volume=0`；`order_flag=1`；`status=48`
  3. **Call RPC**：`await rpc_cancel_order(order_id=orig.order_id)`，try/except 捕获网络异常
  4. **分支处理**：
     - `ack.code == 0` → cancel-row `status=53` `status_msg=已撤`；**同步** INSERT cancel-trade（`volume=orig.volume-orig.traded_volume`、`price=orig.avg_price or orig.price`、`trade_type=1`、`trade_id=CANCEL-{cancel_order_no}-{unix_ts}`、关联 cancel-row 的 order_no）
     - `ack.code != 0` → cancel-row `status=55` `status_msg=ack.msg or 撤单失败`，**不**插 cancel-trade（保留 audit）
     - RPC 抛 Exception → cancel-row `status=55` `status_msg=str(e)`，**不**插 cancel-trade
  5. **WS broadcast**（broker 不推 cancel-row，必须手动 broadcast）：始终推 `order_update`（payload 含 `order_flag=1, user_def, status, status_msg, ...`）；仅成功时推 `trade_update`（payload 含 `trade_type=1, ...`）
- **响应模型**：`CancelResponse { code, msg, cancel_order: Optional[OrderOut] }`（`cancel_order` 是 INSERT 的 cancel-row 的最终状态）
- **OrderOut v9 增** `order_flag: int = 0`；**TradeOut v9 增** `trade_type: int = 0`；Pydantic + inline builder 全链路透传
- **前端约定**：Trade.vue 撤单按钮 → `orderStore.cancelOrder(orderNo, trdDate)` → `api.cancelOrder(orderNo, trdDate)` → `DELETE /api/orders/${orderNo}?trd_date=${trdDate}`
- **前端 holdings 短路**：`applyOrderPush` 见 `order_flag === 1` 时直接 merge + return，**不**走 `_recomputeStatus`（volume=0 会被推算成 49 污染显示）
- **前端视图**：Trade.vue / Orders.vue 加「类型」列（cancel-row 渲染 `el-tag「撤单」`）；Trade.vue 默认过滤隐藏 cancel-row，提供「含撤单审计」选项；`canCancel(row)` 加 `order_flag === 1` 守卫；Trades.vue 买/卖统计排除 `trade_type === 1`
- **实现约定**：`api/orders.py` 中 import 使用别名 `from rpc.client import cancel_order as rpc_cancel_order`，避免与路由函数同名递归

### REQ-TRADE-004: 鉴权

- 全部 `/api/orders` `/api/trades` `/api/asset` 路由必须登录
- `POST /orders/place` 和 `DELETE /orders/{no}` 额外要求 `trader` 或 `admin` 角色

### REQ-TRADE-005: 前端实时性

- 后端 RPC 客户端监听 `EvTrade.Test.Push` 队列
- 收到 `ord_cfm` → 路由到 WS 频道 `order_update`，**status 字段是后端本地推断结果**，前端直接用
- 收到 `trd_cfm` → 路由到 WS 频道 `trade_update`
- 收到资产变更 → `asset_update`（当前**未识别**，待补）

### REQ-TRADE-007: 响应统一性 + list 字段（v8）

- `POST /api/orders/place` 响应模型 `{code, msg, order: OrderOut, list: List[OrderOut]}`
  - `list` 字段是冗余 1 行（与 GET /api/orders 风格统一），前端 axios 拦截器自动解包后 `res.data` 是 1 元素数组
  - 旧 `order` 字段保留（**v8 向后兼容**），不破既有 `r.json()["order"]["order_no"]` 风格调用
- 柜台 RPC 失败时 `list` 也要返（不报错）
- 实施位置：`server/api/orders.py::PlaceOrderResponse` + `_to_order_out` helper
- WS broadcast payload 加 `trd_date + order_no + remark`（供前端推送守门匹配）
- 详见归档 `archive/2026-06-21-order-push-trd-date-authority/spec-deltas/trading.md`

### REQ-TRADE-006: T0 敞口与累计收益（v1）

> 📌 **范围**：本端点只读不写。T0 标签 = `Order.user_def == 'T0'`，由 T0Trade.vue 下单时自动注入。
> 真实已实现盈亏用 `(sell_price - cost_basis) × sell_vol - 费用` 公式（见 `services/t0_aggregate.py::calc_realized_pnl`）。
> 算法独立于 broker 回报延迟：成本基准取自**当前持仓的 `Position.cost_price`**，T+0 减仓时若仓位内含 T-1 底仓则视为锁仓部分，realized 算式仅作用于今日新进仓位的已实现部分。

#### 端点契约

- `GET /api/orders/t0-stats/{stock_code}?trd_date=YYYYMMDD&t0_only=true`
  - **t0_only=false**：当且仅当 `Order.user_def == ''` 不计入；统计所有该 stock_code 当日成交（兼容旧行为，但 realized 改用真实算式）
  - **t0_only=true**：仅 `Order.user_def == 'T0'` 的委托 / 成交计入
  - 响应：`T0StatsOut`（`realized_pnl` 改用真实算式：`(avg_sell - cost_basis) × min(sell_vol, position_vol) - sell_commission - sell_stamp_tax`）
  - **BREAKING**：`realized_pnl` 算式从「买/卖均价差 × 配对量」改为「(卖均价-成本基准)×卖量-费用」；不传 `t0_only` 时，旧实现相当于不区分 T0 标签，新实现仅在 `t0_only=false` 时回退到「全量」

- `GET /api/orders/t0-history/{stock_code}?days=30&t0_only=true` — 行为不变（毛流 diff），但 `t0_only=true` 默认开启是建议而非强制

- `GET /api/orders/t0-exposure?user_def=T0&trd_date=YYYYMMDD`（**新增**）
  - 路径：单日 / 多标的 / 按 `user_def` 聚合
  - 响应：
    ```json
    {
      "trd_date": "20260619",
      "user_def": "T0",
      "positions": [
        {
          "stock_code": "600519.SH",
          "buy_volume": 1000,
          "sell_volume": 800,
          "buy_amount": 180000.0,
          "sell_amount": 145600.0,
          "net_volume": 200,        // = buy_vol - sell_vol（正值=净买入，负值=净卖出）
          "net_amount": 34400.0,    // = buy_amt - sell_amt（净流出）
          "order_count": 5,
          "trade_count": 3,
          "open_order_count": 1
        }
      ],
      "totals": {
        "buy_volume": 5000,
        "sell_volume": 4800,
        "net_volume": 200,
        "buy_amount": 1000000.0,
        "sell_amount": 980000.0,
        "realized_pnl": 1500.0,    // 当日所有标的总真实已实现
        "commission_total": 100.0,
        "stamp_tax_total": 980.0
      }
    }
    ```
  - **关键语义**：`net_volume` 为正 → 净买入敞口 → 一键配平需要"卖出"这些股；为负 → 净卖出 → 需要"补买"
  - 排序：按 `abs(net_amount)` 降序
  - **不要**与 `t0-stats` 重复（那个只算 1 个 stock_code 的当日汇总）

- `GET /api/orders/t0-aggregate?user_def=T0&days=30`（**新增**）
  - 路径：跨多日 / 多标的 / 按 `user_def` 聚合
  - 响应：
    ```json
    {
      "user_def": "T0",
      "days": 30,
      "summary": {
        "total_realized": 5000.0,          // 全期真实已实现（已扣费）
        "total_commission": 500.0,
        "total_stamp_tax": 1500.0,
        "total_buy_amount": 1000000.0,
        "total_sell_amount": 1005000.0,
        "win_days": 18,
        "total_days": 25,
        "win_rate": 0.72,
        "return_rate": 0.005,             // = total_realized / total_buy_amount
        "trade_count": 150,
        "order_count": 80,
        "stocks_traded": 12
      },
      "by_day": [
        {
          "trd_date": "20260619",
          "realized_pnl": 200.0,
          "buy_amount": 50000.0,
          "sell_amount": 50200.0,
          "trade_count": 3,
          "stock_count": 2,
          "cum_pnl": 5000.0
        }
      ],
      "by_stock": [
        {
          "stock_code": "600519.SH",
          "trade_count": 12,
          "realized_pnl": 1200.0,
          "buy_amount": 250000.0,
          "sell_amount": 251200.0
        }
      ]
    }
    ```

#### 计算函数（`services/t0_aggregate.py`）

- `calc_realized_pnl(trades_sell, cost_basis, fee_cfg) -> Tuple[realized, commission, stamp_tax]`
  - 入参：`trades_sell` = 卖方向 Trade 列表（已按 trd_date 过滤）
  - 算法：
    ```
    sell_amt = Σ(t.price * t.volume) for t in trades_sell
    commission = round(sell_amt * fee_cfg.commission_rate, 2)
    stamp_tax = round(sell_amt * fee_cfg.stamp_tax_rate, 2)
    realized = (sell_amt / sell_vol) * sell_vol - cost_basis * sell_vol
              - commission - stamp_tax
             = (avg_sell - cost_basis) * sell_vol - commission - stamp_tax
    ```
  - `cost_basis` 缺省为 0（无当前持仓）→ `realized = -commission - stamp_tax`（仅扣费）
  - 当 `sell_vol == 0` 时返回 `(0, 0, 0)`

- `calc_net_volume(orders, trades) -> Tuple[net_volume, buy_vol, sell_vol, buy_amt, sell_amt]`
  - 基于 Order + Trade 关联，扣失败单（status=55 废单不计入）
  - `net_volume = buy_vol - sell_vol`

#### 实现位置（phase-2 拆分后）

- `server/services/t0_aggregate.py` — facade 兼容垫片（45 行，纯 re-export）
- `server/services/t0_fees.py` — 费率与精度工具（`_q2` / `_q4` / `calc_commission_and_tax` + 共享常量 `_FAILED_STATUS` / `_BUY_TYPE` / `_SELL_TYPE`）
- `server/services/t0_pnl.py` — 真实已实现算法（`calc_realized_pnl`）
- `server/services/t0_aggregators.py` — 分组合并（`calc_net_exposure` / `_order_count_stats` / `_group_by_code` / `aggregate_by_stock` / `aggregate_by_day` / `aggregate_summary` / `apply_user_def_filter`）
- 既有 `from server.services.t0_aggregate import ...` 仍可解析（facade 兜底）
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/spec-deltas/trading.md`

#### 前端约定

- T0Trade.vue 新增组件 `<T0ExposureTable>`：
  - 数据来源：`t0StatsApi.getExposure({ user_def: 'T0' })`
  - 每行展示：代码 / 买量 / 卖量 / 净量 / 净额 / 委托数 / 状态
  - **每行"一键配平"按钮**：调用 `submitOrder({ orderType, volume: |net_volume|, price: latest })`
  - 表头合计行：所有标的的 net_volume 之和（用于"全账户一键配平"）
- T0Trade.vue 新增卡片"📊 T0 累计"：
  - 数据来源：`t0StatsApi.getAggregate({ user_def: 'T0', days: 30 })`
  - 展示：累计已实现、回报率、胜率、胜/总天数、笔数、股票数
  - 切换 7/30/90 天
- `useT0Balance.js` 新增 `exposureList` / `aggregate` 响应式数据 + `loadExposure()` / `loadAggregate()` 加载函数
- 提交下单时 `user_def` 始终为 `'T0'`（已在 T0Trade.vue:743 实现；新增：手动模式 / 一键配平也带 T0 标签）

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
| GET | `/api/system/active-day` | - | login |

## Known Issues (from analysis)

- 🟥 ~~`DELETE /orders/{id}` 之前只改内存假撤单~~ → **本轮已修**（走真 RPC）
- 🟥 ~~`services/trading.py` 118 行内存仓~~ → **本轮已删**
- 🟥 ~~撤单 URL 用 order_id~~ → **v8 已修**（change `2026-06-21-order-push-trd-date-authority`，Trade.vue handleCancel 改传 order_no + trd_date）
- 🟡 前端 `order.js` `cancelOrder` 硬编码 `order.status = '54'`（与后端本地推断不一致）→ 参见 change `2026-06-16-frontend-infer-order-status`
- 🟡 前端 Trade.vue / Orders.vue 状态码分组用了 broker 原始码（55=已成等）而不是后端本地推断码（56=已成）→ 同上 change
- 🟡 `asset_update` 推送功能未实现（RPC 客户端收到资产变更无路由）
- 🟡 价格类型枚举在 api 层用数字、后端 RPC 用数字、文档用文字 → 应统一映射
- 🟢 ~~POST /orders/place 响应缺 list 字段，前端 T0Trade.vue 误读 res.code~~ → **v8 已修**（change `2026-06-21-order-push-trd-date-authority`，list 冗余 1 行 + res 直接是 OrderOut）
- 🟢 ~~前端 5s 轮询 fetchOrders + 缓存双源（orderStore/holdings）~~ → **v8 已修**（change `2026-06-21-order-push-trd-date-authority`，统一 holdings 单一源 + 删 5s 轮询改手动刷新）
