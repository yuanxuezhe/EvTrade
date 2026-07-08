# trading — 委托 / 成交 / 资金

> 📖 **数据结构**详见 [`data-model/spec.md`](../data-model/spec.md) §1（orders / trades / assets）

## Purpose

交易员通过 Web 平台对 QMT 柜台下达买卖指令、查询状态。
**唯一数据源是 QMT 柜台**（通过 msgpacket RPC），后端不维护内存委托/成交副本。

## Requirements

### REQ-TRADE-001: 查询

- `GET /api/orders?stock_code=...&start_date=YYYYMMDD&end_date=YYYYMMDD` — 委托列表（走 `qry_orders`）
  - `start_date` / `end_date` 8 位数字字符串 `^\d{8}$`（Pydantic v1 `Query(regex=...)`）；缺省=激活日 trd_date
  - 过滤谓词 `start_date <= trd_date <= end_date`（仅 `start_date` 时 `trd_date >= start_date`；仅 `end_date` 时 `trd_date <= end_date`）
  - 排序 `ORDER BY order_time DESC`
  - **v12 强化（历史查询核心参数）**：`HistoryOrders.vue` 必须显式传 `start_date` + `end_date`（与可选 `stock_code`）三参数；缺一者返 422。这是历史查询页面的入口契约，与当日 `TodayOrders.vue`（读 Pinia 内存 + IDB）完全分离
- `GET /api/trades?stock_code=...&start_date=YYYYMMDD&end_date=YYYYMMDD` — 成交列表（走 `qry_trades`）
  - 同上区间参数语义
  - 排序 `ORDER BY trade_time DESC, trade_id DESC`（同秒二级 trade_id 兜底；2026-06-30 改：原 `created_at DESC` 与 broker 成交时刻有毫秒级漂移）
  - **v12 强化**：`HistoryTrades.vue` 同上三参数强制
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
- **`OrderOut.status` 语义（v11 broker 字典对齐）**：
  - 委托表 `status` 字段 = **broker xtconstant 字典**（11 条: 48-57 + 255; 与 xtconstant 字典一一对应, 无本地扩展）
  - 推断函数：`_infer_order_status(order, broker_status=None)`（`server/services/order_status.py`，v11 起输出 broker 码）
  - **v11 broker 码业务写入点**（`POST /api/orders/place`）：
    - `place.py:90` 拒单 status: `'55'` (本地废单) → `'57'` (broker JUNK 废单)
    - `place.py:110` RPC 成功 status: `'49'` (本地已报) → `'50'` (broker REPORTED 已报)
    - `place.py:113` RPC 拒单 status: `'55'` (本地废单) → `'57'` (broker JUNK 废单)
  - **v11 终态**：`TERMINAL_STATUSES = ('52','53','54','55','56','57')`（含 broker 52=部成待撤, 与 broker 终态口径一致）
  - **v8 规则改**（历史保留）：以 `cancelled_volume` 主轴
    - `cancelled_volume >= volume` → 54（broker 已撤）
    - `cancelled_volume > 0 && traded_volume > 0` → 53（broker 部成部撤）
    - `cancelled_volume > 0`（无成交）→ 54
    - `broker_status in (51,52,53,54)` 兼容老 broker 协议（broker 码）
    - 累计推断：`traded_volume` 决定 50/51
  - 终态 (broker 52/53/54/55/56/57) 一旦写入不再被 trd_cfm 覆盖
  - **前端必须镜像同一函数**：`client/src/utils/format.js` 提供 `inferOrderStatus(order, brokerStatus?)`，见 `frontend/spec.md` REQ-FE-006
  - `OrderOut` v8 增 `cancelled_volume` 字段（默认 0），由 `handle_ord_cfm` 累加 broker 推送的撤单量

#### Scenario: place.py RPC 成功写入 broker 50（v11 修订）

- **WHEN** POST /api/orders/place 收到 `stock_code, order_type, volume, price, price_type` 且 RPC 返回 `code=0`
- **THEN** Order.status = `'50'`（broker REPORTED 已报），不是本地推断码 '49'

#### Scenario: place.py RPC 拒单写入 broker 57（v11 修订）

- **WHEN** POST /api/orders/place 收到 RPC 返回 `code != 0`（拒单）
- **THEN** Order.status = `'57'`（broker JUNK 废单），不是本地推断码 '55'

#### Scenario: place.py 同步写 cancelled_volume=volume（v8 不变）

- **WHEN** POST /api/orders/place 收到 RPC 返回 `code != 0`（拒单）
- **THEN** Order.cancelled_volume = Order.volume（一次性抹平, change `system-delegation-price-fill-calc` 起 5 类写入路径之一 R2a）
- **v7 schema 调整**：
  - `Order` 表删除 `client_order_id` 字段（不下发，幂等不再靠 DB UNIQUE 约束）
  - `Order` 表删除 `uq_orders_client_trd` / `uq_orders_broker_id` 约束（order_id 下单时为空，broker 约束不可靠）
  - `Order` 表新增 `user_def` 字段（`String(255)`，默认空字符串）记录外部自定义信息（前端幂等号 / 备注）
  - `Trade` 表删除 `order_id` 字段（broker 号在 trd_cfm 到达时可能尚未到达）
  - `Trade` 表新增 `order_no` 字段并入 PK（PK = `(trd_date, order_no, trade_id)`），关联键更稳定
  - 下单 API `POST /api/orders/place` 接受可选 `user_def` 字段透传（无业务约束，仅落库）
  - 下单幂等改由 `order_no` 单调递增保证（同 ord_stk RPC 第二次调用方会被 broker 拒绝）

### REQ-TRADE-003: 撤单（v11 broker 码业务写入点 + v13 raw_id 结构化冗余）

DELETE 端点业务写入点固定码 MUST 改 broker 码：
- `cancel.py:74` cancel-row 起手 status: `'48'` (本地 sentinel, 保留)
- `cancel.py:115` DELETE 成功 status: `'53'` (本地已撤) → `'54'` (broker CANCELED 已撤)
- `cancel.py:144` DELETE 失败 status: `'55'` (本地废单) → `'57'` (broker JUNK 废单)
- `cancel.py:61` pre-check `if order.status not in ("48","49")` → `("48","49","50")`（含 broker 50=已报）

- `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD`
- **v6 BREAKING**：URL 参数从 `order_id` 改为 `order_no`（本地 8 位序号）；后端按 `(trd_date, order_no)` 定位 Order
- **v9 BREAKING**：DELETE 端点**立即 INSERT 一条 cancel-row**（`order_flag=1`），用于本地撤单审计；broker 不会推这个 row（broker `ord_cfm` 的 `remark` 永远是**原委托**的 `order_no`，不会回带 cancel-row 的 `order_no`）
- **v13 ENHANCE**：INSERT cancel-row 时**同时**写 `raw_id = orig.order_no`（结构化冗余；`user_def` 仍 = `"CANCEL:{orig_order_no}"` 不动）；WS broadcast payload 增加 `raw_id` 字段
- **5 步流程**：
  1. **Pre-checks**（v11 broker 码）：原委托 `status` 不在 `{48,49,50}` → 返 `{code: NO_CANCELABLE}`，**不插行**；`order_id` 缺失 → 返 `{code: NO_ORDER_ID, http=409}`，**不插行**
  2. **INSERT cancel-row**（v13 增 raw_id，commit 立即落库避免 RPC 异常时孤儿）：`order_no = next_order_no(db)`；`user_def = "CANCEL:{orig_order_no}"`；**`raw_id = orig.order_no`（v13 NEW 结构化冗余）**；`stock_code/order_type/price_type/price` 镜像；`volume=0`；`order_flag=1`；`status=48`（broker UNREPORTED 本地 sentinel）
  3. **Call RPC**：`await rpc_cancel_order(order_id=orig.order_id)`，try/except 捕获网络异常
  4. **分支处理**（v11 broker 码）：
     - `ack.code == 0` → cancel-row `status=54`（broker CANCELED 已撤） `status_msg=已撤`；**同步** INSERT cancel-trade（`volume=orig.volume-orig.traded_volume`、`price=orig.avg_price or orig.price`、`trade_type=1`、`trade_id=CANCEL-{cancel_order_no}-{unix_ts}`、关联 cancel-row 的 order_no）
     - `ack.code != 0` → cancel-row `status=57`（broker JUNK 废单） `status_msg=ack.msg or 撤单失败`，**不**插 cancel-trade（保留 audit）
     - RPC 抛 Exception → cancel-row `status=57`（broker JUNK 废单） `status_msg=str(e)`，**不**插 cancel-trade
  5. **WS broadcast**（broker 不推 cancel-row，必须手动 broadcast）：始终推 `order_update`（payload 含 `order_flag=1, user_def, status, status_msg, raw_id, ...`，status 是 broker 码 54 或 57）；仅成功时推 `trade_update`（payload 含 `trade_type=1, ...`）

#### Scenario: cancel.py DELETE 成功写入 broker 54（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用 RPC 返回 `ack.code == 0`
- **THEN** cancel-row.status = `'54'`（broker CANCELED 已撤），不是本地推断码 '53'

#### Scenario: cancel.py DELETE 失败写入 broker 57（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用 RPC 返回 `ack.code != 0` 或抛 Exception
- **THEN** cancel-row.status = `'57'`（broker JUNK 废单），不是本地推断码 '55'

#### Scenario: cancel.py pre-check 含 broker 50（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用, 原委托 status='50'（broker 已报）
- **THEN** pre-check 通过（status 在 {48, 49, 50} 内）, 进入 INSERT cancel-row + RPC 流程

#### Scenario: cancel.py pre-check 拒绝 broker 终态（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用, 原委托 status='54'（broker 已撤）
- **THEN** pre-check 拒绝（status 不在 {48, 49, 50} 内）, 返 `{code: NO_CANCELABLE}`, 不插行

#### Scenario: cancel.py 同步写原 cancelled_volume=volume（v11 修订 + R1 兜底）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用, RPC 返回 `ack.code == 0`
- **THEN** orig.cancelled_volume = orig.volume（一次性抹平, R1, change `system-delegation-price-fill-calc` 起 5 类写入路径之一）

- **响应模型**：`CancelResponse { code, msg, cancel_order: Optional[OrderOut] }`（`cancel_order` 是 INSERT 的 cancel-row 的最终状态）
- **OrderOut v9 增** `order_flag: int = 0`；**TradeOut v9 增** `trade_type: int = 0`；Pydantic + inline builder 全链路透传
- **前端约定**：Trade.vue 撤单按钮 → `orderStore.cancelOrder(orderNo, trdDate)` → `api.cancelOrder(orderNo, trdDate)` → `DELETE /api/orders/${orderNo}?trd_date=${trdDate}`
- **前端 holdings 短路**：`applyOrderPush` 见 `order_flag === 1` 时直接 merge + return，**不**走 `_recomputeStatus`（volume=0 会被推算成 50 污染显示）
- **前端视图**：Trade.vue / Orders.vue 加「类型」列（cancel-row 渲染 `el-tag「撤单」`）；Trade.vue 默认过滤隐藏 cancel-row，提供「含撤单审计」选项；`canCancel(row)` 加 `order_flag === 1` 守卫；Trades.vue 买/卖统计排除 `trade_type === 1`
- **实现约定**：`api/orders.py` 中 import 使用别名 `from rpc.client import cancel_order as rpc_cancel_order`，避免与路由函数同名递归

### REQ-TRADE-002.1: ord.py R2b 触发条件 broker 终态（v11 修订）

`server/services/push/ord.py` R2b 触发条件 MUST 用 broker xtconstant 终态口径:
- R2b 触发条件 `broker_status in ('53','55')` (本地已撤/本地废单) → `('52','53','54','55','56','57')` (broker 全部终态)
- rule 3 触发 `broker_status in ('52','53','54')` (本地撤单类) → `('51','52','53','54')` (broker 撤单类: 51=已报待撤, 52=部成待撤, 53=部成部撤, 54=已撤)

#### Scenario: ord.py R2b broker 终态触发（v11 修订）

- **WHEN** broker 推 `ord_cfm` row 含 `order_status='54'`（broker 已撤）
- **AND** Order.cancelled_volume < Order.volume
- **THEN** order.cancelled_volume = order.volume（R2b 抹平, change `system-delegation-price-fill-calc` 起 5 类写入路径之一）

#### Scenario: ord.py rule 3 broker 撤单类触发（v11 修订）

- **WHEN** broker 推 `ord_cfm` row 含 `order_status='52'`（broker 部成待撤）
- **THEN** _infer_order_status 触发 rule 3, 输出 status='54'（broker 已撤）或 '53'（broker 部成部撤）或 '56'（broker 已成），按 cum_traded 决定

### REQ-TRADE-004: 鉴权

- 全部 `/api/orders` `/api/trades` `/api/asset` `/api/positions` 路由必须登录
- `POST /orders/place` 和 `DELETE /orders/{no}` 额外要求 `trader` 或 `admin` 角色
- **v12 新增（admin-only 调平）**：
  - `PUT /api/asset/adjust`
  - `PUT /api/positions/{stock_code}/adjust`
  - 均必须 role=admin（`require_admin` 直接挂端点 dependency，不走 `_AUTH`）

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

### REQ-TRADE-010: 下单前置 disabled 校验（v17 t0-trade-polish-bundle commit 2）

> 前端 UI 必须在用户点 [买 / 卖 / 配平] 按钮之前, 校验资金/持仓足够, 否则禁用按钮 + tooltip 注明缺额。
> 与后端 broker PriceCalc.compute_required 同口径 (`need = qty * price`), 不存在双源。

#### Scenario: 资金不足买按钮 disabled

- **WHEN** 主表买按钮触发, `asset.cash < qty * price` (走 `lib/t0-calc.calcInsufficientCash`)
- **THEN** MUST 禁用按钮 + tooltip "资金 ¥X 不足 (需 ¥X, 现有 ¥X)"
- **AND** 后端 RPC 仍接受并按 broker 规则拒单 (前端 disabled 是 UX 优化, 不是后端拦截)

#### Scenario: 持仓不足卖按钮 disabled

- **WHEN** 主表卖按钮触发, `currentVolume < sellQty` (走 `lib/t0-calc.calcInsufficientPosition`)
- **THEN** MUST 禁用按钮 + tooltip "持仓 X 股不足, 缺 Y 股"
- **AND** 与 broker `Position.avl_vol` 口径对齐 (avl_vol 优先, vol 兜底)

#### Scenario: 配平按钮按 side 分别校验

- **WHEN** 配平按钮触发, side=buy (净卖锁仓) → 查 cash; side=sell (净买锁仓) → 查持仓
- **THEN** 任意一边不足 MUST 禁用 + tooltip 注明哪边不足

#### Scenario: 校验公式与 broker 同口径

- **WHEN** 前端计算 `need = qty * price`
- **THEN** MUST 与 `server/services/order_calc.py::PriceCalc.compute_required` 输出同公式, 单测覆盖 0/NaN/负数/边界

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

### REQ-TRADE-008: orders API 模块结构（phase-2 拆分）

`server/api/orders.py` 历史上集中了 4 个 Pydantic schema、4 个端点函数（place/cancel/list/history）和 1 个 `_to_order_out` helper，单文件 482 行混合 5 类职责。phase-2 拆分目标：每个文件单一职责 + facade 兼容。

#### 物理拆分

| 文件 | 职责 | 行数 | 关键导出 |
|---|---|---|---|
| `server/api/_order_schemas.py` | Pydantic schemas + helper | ~92 | `PlaceOrderRequest`, `OrderOut`, `PlaceOrderResponse`, `ListOrdersResponse`, `CancelResponse`, `_to_order_out` |
| `server/api/order_place.py` | POST /place 端点 | ~143 | `register_place(router)` |
| `server/api/order_cancel.py` | DELETE /{order_no} 端点 | ~191 | `register_cancel(router)` |
| `server/api/order_query.py` | GET '' + GET /history 端点 | ~95 | `register_query(router)` |
| `server/api/orders.py`（facade） | 装配 + monkeypatch 兼容 | ~58 | `router`, `ord_stk`, `rpc_cancel_order`, `ws_manager`, 5 个 schema, `_to_order_out` |

#### Facade 必须满足

1. **`from server.api.orders import router`** — `main.py: app.include_router(orders.router, ...)` 0 改动
2. **顶层 import** `ord_stk` / `rpc_cancel_order` / `ws_manager` — `test_orders_api.py` 通过 `monkeypatch.setattr("api.orders.ord_stk", mock)` 等路径打补丁
3. **顶层 re-export** 全部 5 个 Pydantic + `_to_order_out` — 兼容既有 import 路径

#### Late import 模式（**强制**）

`order_place.py` / `order_cancel.py` 端点函数体内**必须**通过

```python
from server.api.orders import ord_stk, ws_manager   # 端点函数体首行
```

拿被 patch 后的符号，**不允许**模块顶部直接 `from server.rpc.client import ord_stk`（否则 monkeypatch 不生效）。

#### Router 装配（facade 模式）

```python
# orders.py (facade)
router = APIRouter()
register_place(router)
register_cancel(router)
register_query(router)
```

3 个子模块共享同一 router 实例，端点装饰器 `@router.post("/place", ...)` 在 `register_*` 函数体内执行。

#### 验证清单

- `python -c "from server.api.orders import router; print(len(router.routes))"` → 4
- `python -c "from server.main import app"` 0 异常
- `pytest server/test_orders_api.py` 可被 R6 已知问题阻塞（pre-existing "Table 'orders' already defined"），import 完整性必须通过
- 21 个端点路径不变：POST /api/orders/place、DELETE /api/orders/{order_no}、GET /api/orders、GET /api/orders/history

### REQ-TRADE-009: 资金 / 持仓调平 API（v12 新增）

admin 资金 / 持仓盘中调平端点，**核心合约**详见 `asset-position-adjust/spec.md`。本节给出在 trading 域的鉴权约束与归宿。

- `PUT /api/asset/adjust` —— 同 `asset.py` router（facade），实现 `server/api/asset_adjust.py`
- `PUT /api/positions/{stock_code}/adjust` —— 同 `positions.py` router（facade），实现 `server/api/position_adjust.py`

#### Scenario: 资金调增

- **WHEN** admin 调 `PUT /api/asset/adjust { delta_cash: 1000.0, reason: "银证转账入金" }`
- **THEN** 响应 `{code: 0, asset: { cash: 6000.0, synced_from: "manual", ... }}`
- **AND** DB `Asset.cash += 1000.0`、`Asset.synced_from = "manual"`

#### Scenario: 持仓调增 vol + 不动 avl_vol

- **WHEN** admin 调 `PUT /api/positions/600030.SH/adjust { delta_vol: 100 }`
- **AND** Position row 已存在
- **THEN** `Position.vol += 100`，`Position.avl_vol` 不变
- **AND** `Position.synced_from = "manual"`

#### Scenario: 不存在的 stock_code → 404

- **WHEN** admin 调 `PUT /api/positions/UNKNOWN/adjust { delta_vol: 100 }`
- **THEN** 返 `404` + `{detail: "POSITION_NOT_FOUND: no Position for stock_code=UNKNOWN"}`
- **AND** 不自动新建 Position 行（防误操作）

#### Scenario: trader → 403 / 未登录 → 401

- **WHEN** trader 调任一调平端点
- **THEN** 返 403 `需要管理员权限`
- **WHEN** 无 token 调任一调平端点
- **THEN** 返 401 `未登录或登录已过期`

#### Scenario: 缺 delta_* 字段 → 422

- **WHEN** admin 调 `PUT /api/asset/adjust {}` 或 `PUT /api/positions/{stock_code}/adjust {}`
- **THEN** 返 422 `at least one of delta_* required`

#### 边界（设计约束）

- 负数允许（broker 可透支 / 仓位可临时负值），不抛 ValueError
- `reason` 仅入 log，不入库（用户不留 audit row）
- 不引入 `manual_offset_*` 字段，调平值直接体现在 `cash` / `total_asset` / `vol` / `avl_vol` 上
- 下次 `do_reconcile` 全表覆盖会重置 `synced_from = "rpc_full"`，调平值被 broker 真实值覆盖


### Requirement: 历史查询参数契约（v12 强化）

`GET /api/orders` 与 `GET /api/trades` 的 `start_date` / `end_date` / `stock_code` 参数 MUST 被前端 `HistoryOrders.vue` 与 `HistoryTrades.vue` 显式传参使用，作为历史查询的核心入口。**缺省时** = 激活日 trd_date（保持现状，向后兼容）。

#### Scenario: HistoryOrders.vue 调起查询

- **WHEN** admin 在 HistoryOrders.vue 点"查询"按钮
- **THEN** 构造 `getOrders({ startDate: 'YYYYMMDD', endDate: 'YYYYMMDD', stockCode: '...' })` opts 对象
- **AND** 至少传 `startDate` 与 `endDate`（`stockCode` 可空）
- **AND** 后端响应在 `startDate <= trd_date <= endDate` 区间内 + 可选 `stock_code == stockCode` 过滤

#### Scenario: 参数校验失败返 422

- **WHEN** 前端传 `startDate > endDate` 或缺一者
- **THEN** 后端 Pydantic 校验失败，返 422
- **AND** 前端 axios 拦截器弹 ElMessage.error

### Requirement: 资金调平 API 契约（v12 新增段）

`PUT /api/asset/adjust` MUST 接受 `delta_cash` / `delta_total_asset` 可选 float，对 `Asset.cash` / `Asset.total_asset` 做原子 `+=`，并打 `synced_from="manual"` 标记。**complete contract** 见 `asset-position-adjust/spec.md`。

#### Scenario: 调增资金

- **WHEN** admin 调 `PUT /api/asset/adjust { delta_cash: 1000.0, reason: "银证转账" }`
- **THEN** `Asset.cash += 1000.0`
- **AND** `Asset.synced_from = "manual"` + `Asset.synced_at = utcnow`
- **AND** 响应 `{ code: 0, msg: "ok", asset: { ...AssetOut } }` 让前端 watcher 拿到新值

#### Scenario: 调减资金（资金为负）

- **WHEN** `Asset.cash = 500.0`，admin 调 `delta_cash: -800.0`
- **THEN** `Asset.cash = -300.0`（允许为负，broker 真实可透支）
- **AND** 不抛 ValueError（不限制 >= 0）

#### Scenario: 授权

- **WHEN** 任何用户调 `PUT /api/asset/adjust`
- **THEN** 必须 login 且 role=admin
- **AND** 非 admin 返 403

### Requirement: 持仓调平 API 契约（v12 新增段）

`PUT /api/positions/{stock_code}/adjust` MUST 接受 `delta_vol` / `delta_avl_vol` 可选 int，对 `Position.vol` / `Position.avl_vol` 做原子 `+=`，并打 `synced_from="manual"` 标记。**complete contract** 见 `asset-position-adjust/spec.md`。

#### Scenario: 调增持仓总量

- **WHEN** admin 调 `PUT /api/positions/600030.SH/adjust { delta_vol: 100, reason: "期权行权" }`
- **THEN** `Position.vol += 100`
- **AND** `Position.avl_vol` 不变（除非也传 `delta_avl_vol`）
- **AND** `Position.synced_from = "manual"`

#### Scenario: stock_code 不存在的 Position

- **WHEN** admin 调 `PUT /api/positions/UNKNOWN/adjust { delta_vol: 100 }`
- **THEN** 后端返 404 `{ code: POSITION_NOT_FOUND, msg: "no Position for stock_code=..." }`
- **AND** 不会自动新建 Position（防止误操作）

#### Scenario: 授权

- 同 `PUT /api/asset/adjust`，必须 role=admin



### Requirement: today / history 视图拆分（v12）

`client/src/views/Orders.vue` 与 `Trades.vue` MUST 被拆分为 4 个独立 view + 4 个独立路由：

| 旧路由 | 新路由拆分 |
|---|---|
| `/orders`（混合当日+历史） | `/today/orders` + `/history/orders` |
| `/trades`（混合当日+历史） | `/today/trades` + `/history/trades` |

详见 `intraday-orders-trades-cache/spec.md` 与 `orders-trades-history-query/spec.md`。

#### Scenario: 旧路由重定向兼容

- **WHEN** user 导航到 `/orders` 或 `/trades`
- **THEN** router 重定向到 `/today/...` 对应路由（旧书签兼容）

### REQ-TRADE-011: Order.user_def 关联约定 + IX_ORDERS_USER_DEF + T0 端点 JOIN 迁移（strategy_trade）

`strategy` 引擎触发的下单与历史 T0 委托的归属查询需要统一的 `user_def` 关联约定。

- **`Order.user_def = str(strategy.id)`**：strategy 引擎下单时把 strategy 主键 int 序列化为字符串写入 `user_def` 列
  - 与字面量 `"T0"` 共存（人工 T0 单仍写 `"T0"`，strategy 自动单写 `"5"`、`"7"` 等）
- **索引 `ix_orders_user_def`**：在 `Order` 表加 B-tree 索引支撑 T0 端点 JOIN 过滤
  - `server/models/orm.py::Order.Index("ix_orders_user_def", "user_def")`
  - `server/db.py::init_db` 幂等迁移：`CREATE INDEX IF NOT EXISTS ix_orders_user_def ON orders(user_def)`
- **T0 端点 JOIN 迁移**（`server/api/t0_stats.py` + `t0_aggregate.py`）：
  - `Order.user_def == "T0"` → `Order.user_def.in_(resolve_t0_user_defs(db, "T0"))`
  - `resolve_t0_user_defs(db, user_def) -> Optional[Set[str]]`：返 Set[str]，含字面量 `"T0"` + 所有 `type='t0'` strategy.id 的字符串化
  - `apply_user_def_filter(..., db=db)`：可选 db 参数，无 db 时回退到旧字面量集合（向后兼容）
  - 影响端点：`t0_stats` / `t0_history`（spec 误写为 `t0_trades`）/ `t0_exposure` / `t0_aggregate`
- 与 REQ-TRADE-002 一致：`remark` 字段透传 `order_no`

#### Scenario: strategy 委托 user_def=str(id)

- **GIVEN** strategy.id=5
- **WHEN** grid 触发下单
- **THEN** Order.user_def MUST = "5"

#### Scenario: T0 端点含 t0 strategy 单子

- **GIVEN** strategy id=7, type=t0
- **WHEN** GET /api/t0/stats?t0_only=true
- **THEN** MUST 包含 user_def in {"T0", "7"} 的委托

#### Scenario: 旧调用无 db 兼容

- **GIVEN** apply_user_def_filter(..., db=None) 被旧代码调用
- **THEN** MUST 回退到 {"T0"} 字面量集合（行为不变）

#### Scenario: 委托/成交视图按 today/history 拆分

- **WHEN** 实施本 change
- **THEN** `TodayOrders.vue` / `TodayTrades.vue` 读 `useHoldingsStore()` (Pinia + IDB write-through, 无 HTTP)
- **AND** `HistoryOrders.vue` / `HistoryTrades.vue` 走局部 HTTP 查询, 不入 IDB

### REQ-TRADE-012: cancel-row.raw_id 字段契约（v13 NEW，layered-architecture-and-strategy-master）

`Order.raw_id` 是 cancel-row 专属字段，提供与 `user_def` 并存的结构化关联。

- **`Order.raw_id` 写入规则**：
  - DELETE 端点 INSERT cancel-row 时写入：`raw_id = orig.order_no`
  - place 端点 INSERT 普通行时：`raw_id = NULL`
  - broker `ord_cfm` 不写 `raw_id`（broker 不知道这个本地概念）
  - 旧数据全 NULL（迁移脚本不强制回填）
- **`raw_id` 与 `user_def` 关系**：
  - `user_def = f"CANCEL:{orig.order_no}"`（v9 约定，远程 v9 audit 兼容，纯字符串）
  - `raw_id = orig.order_no`（v13 新增，结构化字段，`String(8)` 纯数字）
  - 两者表达同一关联（cancel-row → 父委托），但 `raw_id` 是结构化字段（query / JOIN 友好）
- **前端 / 后端 query 优先用 `raw_id` 做结构化 JOIN / 过滤**；`user_def` 保留作 audit 兼容
- **不新增** `raw_id` 索引（cancel-row query 走 `WHERE trd_date=? AND order_no=?` 已有 PK 覆盖；`raw_id` 单列查询少）
- **不动** `ix_orders_user_def` 索引（远程 `2026-07-05-strategy_trade` 已加）
- **冗余可接受**：未来如彻底迁移到 `raw_id`，可走独立的 deprecation 流程；本 change 不动 `user_def` 既有写入规则
- **WS broadcast payload**：`order_update` payload 增加 `raw_id` 字段（值同 INSERT 时 = `orig.order_no`），前端 `holdings.applyOrderPush` 透传此字段到 IDB

#### Scenario: cancel-row 双重字段冗余校验（v13 NEW）

- **GIVEN** 数据库中存在 `order_flag=1` 的 cancel-row
- **WHEN** 系统校验该行
- **THEN** MUST 同时满足：`user_def LIKE "CANCEL:%"` **AND** `raw_id` 非 NULL **AND** `raw_id = substr(user_def, 8)`（即 user_def 的 8 位数字 = raw_id）

#### Scenario: 反向查询 parent ↔ cancel（v13 NEW）

- **GIVEN** 数据库中存在 cancel-row（order_flag=1, raw_id='10000007'）
- **WHEN** 执行 `SELECT orig.* FROM orders AS orig JOIN orders AS cancel ON cancel.raw_id = orig.order_no WHERE cancel.order_flag = 1`
- **THEN** MUST 返回原委托（order_no='10000007'）

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
| PUT | `/api/asset/adjust` | - | **admin** （v12 调平） |
| GET | `/api/positions` | - | login |
| PUT | `/api/positions/{stock_code}/adjust` | - | **admin** （v12 调平） |
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


---

# v18 Sync (change `2026-07-08-t0-task-management`)

> 2026-07-08 sync — 完整 spec delta 段已落库, 详见 archive change。

## ADDED Requirements

### Requirement: REQ-TRADE-013 T0Task 一等公民实体（v18）

平台 MUST 把"做 T 任务"作为一等公民实体持久化，区别于 `Order.user_def = 'T0'` 的隐式标签：

- **`T0Task`** 表字段：
  - `id` int PK auto_increment
  - `user_id` int NOT NULL — owner
  - `stock_code` varchar(16) NOT NULL
  - `base_volume` int NOT NULL DEFAULT 0 — 底仓量（"保留部分底仓"语义）
  - `target_volume` int NOT NULL DEFAULT 0 — 目标开仓量（区别于现仓位的净增量）
  - `coefficient` float NOT NULL DEFAULT 1.0 — 复用 REQ-TRADE-005 配平系数
  - `status` enum('active','closed','archived') NOT NULL DEFAULT 'active'
  - `note` varchar(255) — 用户备注
  - `created_at` / `closed_at` datetime
  - `created_trd_date` varchar(8) — 创建日交易日（业务字段，不用创建时间倒推）

- **Order 表加 `task_id`**：
  - `task_id` int NULL — 可选 FK → `t0_tasks.id`
  - **与 `user_def = 'T0'` 共存**：新建 task 后的单同时写 `user_def='T0'` AND `task_id=<id>`；无 task 的旧 T0 单 `task_id IS NULL` + `user_def='T0'`
  - 加索引 `ix_orders_task_id`

- **创建规则**：
  - `base_volume` 必须 `>= 0`
  - `target_volume` 可以为负数（净减仓目标）
  - `base_volume + target_volume` = 任务终态持仓目标

#### Scenario: 基于现仓位建任务

- **GIVEN** 现仓位 `Position{stock_code: '600519.SH', vol: 1000, cost_price: 1500}`
- **WHEN** `POST /api/t0-tasks { stock_code: '600519.SH', base_volume: 1000, target_volume: 2000 }`
- **THEN** 创建 task `id=5, base_volume=1000, target_volume=2000, status='active'`
- **AND** task 净敞口初值 = 0（建任务时不立即建仓位；现仓位归到 base_volume）

#### Scenario: 0 持仓建任务

- **GIVEN** `Position{stock_code: '002594.SH'}` 不存在
- **WHEN** `POST /api/t0-tasks { stock_code: '002594.SH', base_volume: 0, target_volume: 1000 }`
- **THEN** 创建 task `base_volume=0, target_volume=1000, status='active'`
- **AND** 用户后续手动买入 1000 股 → 归到该 task

#### Scenario: 旧 T0 单不带 task_id

- **GIVEN** 已有 `Order{user_def: 'T0', task_id: NULL}`
- **WHEN** 跑 `/api/t0-stats/600519.SH?t0_only=true`
- **THEN** 仍然包含此单（向后兼容：旧 path 走 user_def 聚合）
- **AND** `/api/t0-tasks/{id}/stats` 不包含此单（task 维度只看 task_id 关联单）

#### Scenario: task_id NOT NULL constraint

- **WHEN** migration `add-t0-tasks.py` 跑
- **THEN** 表创建幂等（`CREATE TABLE IF NOT EXISTS t0_tasks`）
- **AND** `ALTER TABLE orders ADD COLUMN task_id INT NULL` 幂等（检测列存在则跳过）
- **AND** `CREATE INDEX ix_orders_task_id ON orders(task_id)` 幂等

### Requirement: REQ-TRADE-014 T0Task CRUD API（v18）

后端 MUST 暴露以下 REST 端点：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/t0-tasks` | `POST` | 创建任务 |
| `/api/t0-tasks` | `GET` | 列表（支持 `?status=active` / `?stock_code=` / `?days=30`） |
| `/api/t0-tasks/{id}` | `GET` | 详情（含统计 + 当日净敞口） |
| `/api/t0-tasks/{id}` | `PATCH` | 改 note / coefficient / status（`status` 仅允许 `active ↔ closed`，归档用 DELETE） |
| `/api/t0-tasks/{id}` | `DELETE` | 仅 `archived` 状态可删（防误操作） |
| `/api/t0-tasks/{id}/balance` | `POST` | 一键配平（按 task 净敞口 - base_volume） |
| `/api/t0-tasks/{id}/close` | `POST` | 关任务（强制配平净敞口 → 改 status=closed → 设 closed_at） |
| `/api/t0-tasks/{id}/stats` | `GET` | 统计（已实现 + 未实现 + 累计天数 + 胜率） |

#### Scenario: 创建任务鉴权

- **WHEN** 非 `trader` / `admin` 角色 `POST /api/t0-tasks`
- **THEN** MUST 返回 `403`
- **AND** admin 可看所有 user_id 的 task；trader 只能看自己的

#### Scenario: balance 配平公式

- **GIVEN** task `id=5, base_volume=1000, target_volume=2000`，已成交 task 内 `buy_vol=2000, sell_vol=300`
- **WHEN** `POST /api/t0-tasks/5/balance { coefficient: 1.0 }`
- **THEN** `task_net_volume = buy_vol - sell_vol = 1700`
- **AND** `task_target = base_volume + target_volume = 3000`
- **AND** `balance_volume = task_target - (task_net_volume + current_position_vol)`（按现仓位算缺口）
- **AND** 若 `balance_volume > 0` → 提交买单 `volume=round_to_lot(balance_volume * coefficient, 'BUY')`；否则提交卖单
- **AND** 提交的单 MUST 写 `task_id=5` AND `user_def='T0'`

#### Scenario: balance 资金/持仓前置校验

- **WHEN** `balance_volume > 0` 但 `asset.cash < balance_volume * price`
- **THEN** MUST 拒绝，返回 `409 Conflict`，body `{detail: '资金不足, 需 ¥X 现有 ¥X'}`
- **WHEN** `balance_volume < 0` 但 `Position{stock_code}.avl_vol < |balance_volume|`
- **THEN** MUST 拒绝，返回 `409 Conflict`，body `{detail: '持仓不足, 缺 X 股'}`
- **AND** 与 REQ-TRADE-010 前端 disabled 校验同口径

#### Scenario: close 强制配平

- **WHEN** `POST /api/t0-tasks/5/close`
- **THEN** 先按 REQ-TRADE-014 balance 逻辑配平到 `base_volume`（**保留底仓**）
- **AND** 配平成功 → `status='closed'`，`closed_at=now()`
- **AND** 配平失败 → `status` 不变，返回错误，调用方需手动处理

#### Scenario: delete 仅 archived 可删

- **WHEN** `DELETE /api/t0-tasks/5` 且 `status='active'`
- **THEN** MUST 拒绝，返回 `409 Conflict`
- **WHEN** `DELETE /api/t0-tasks/5` 且 `status='archived'`
- **THEN** 删除该 task 记录（**不级联删除 orders**，保留审计）

#### Scenario: 列表按状态过滤

- **WHEN** `GET /api/t0-tasks?status=active`
- **THEN** MUST 只返 `status='active'` 的 task
- **AND** 按 `created_at DESC` 排序
- **AND** 每行附带 `summary`：`{task_net_volume, realized_pnl, unrealized_pnl, position_vol}`

### Requirement: REQ-TRADE-015 T0Task 统计维度（v18）

`GET /api/t0-tasks/{id}/stats` MUST 返回：

```json
{
  "task": { "id": 5, "stock_code": "...", "status": "active", "base_volume": 1000 },
  "summary": {
    "task_net_volume": 700,           // task 内 buy_vol - sell_vol（不含建任务前现仓）
    "position_vol": 1700,              // 当前持仓（含 task 外底仓）
    "task_attributed_vol": 700,       // = task_net_volume, 任务贡献
    "realized_pnl": 1200.0,            // task 内卖出 pnl - 卖 fee - 卖 tax
    "unrealized_pnl": 350.0,          // (last_price - cost_basis) * task_net_volume
    "commission_total": 50.0,
    "stamp_tax_total": 80.0,
    "trade_count": 12,
    "order_count": 8,
    "first_trd_date": "20260701",     // task 内最早交易日
    "last_trd_date": "20260708",
    "trading_days": 6,
    "winning_days": 4,                 // 当日 realized_pnl > 0 的天数
    "win_rate": 0.667
  },
  "daily": [
    { "trd_date": "20260701", "buy_vol": 500, "sell_vol": 0, "net_vol": 500, "realized_pnl": 0, "cum_pnl": 0 },
    { "trd_date": "20260702", "buy_vol": 0, "sell_vol": 300, "net_vol": -300, "realized_pnl": 600, "cum_pnl": 600 },
    ...
  ],
  "by_stock": [...]                   // 任务都是 1 个 stock_code，但保持 schema 对齐 REQ-TRADE-006
}
```

#### Scenario: realized_pnl 计算口径

- **WHEN** task 内卖单 `price=15, volume=300`，task 内买单均价 `cost_basis=14`
- **THEN** `realized_pnl = (15 - 14) * 300 - commission - stamp_tax`
- **AND** `commission = round(4500 * fee_cfg.commission_rate, 2)`；`stamp_tax = round(4500 * fee_cfg.stamp_tax_rate, 2)`
- **AND** 复用 `services/t0/pnl.py::calc_realized_pnl`

#### Scenario: unrealized_pnl 计算口径

- **WHEN** task 内 `task_net_volume=700, cost_basis=14, last_price=14.5`
- **THEN** `unrealized_pnl = (14.5 - 14) * 700 = 350`
- **AND** `last_price` 走 `useQuoteStore().getLastPrice(stock_code)`，无 quote 时走 `Position.cost_price` 兜底
- **AND** `unrealized_pnl` 不扣预期费用（前端展示时另算 "扣费后未实现"）

#### Scenario: winning_days 统计

- **WHEN** task 跨 6 个交易日，每日 realized_pnl = [+200, -100, +300, 0, +50, -30]
- **THEN** `winning_days = 4`（包含 0；明确大于 0 才算胜）
- **AND** `trading_days = 6`
- **AND** `win_rate = 4 / 6 ≈ 0.667`

#### Scenario: 无关联单

- **WHEN** task 建完无任何成交
- **THEN** MUST 返回 `task_net_volume=0, realized_pnl=0, unrealized_pnl=0, trading_days=0`
- **AND** 不抛错，`daily=[]`

### Requirement: REQ-TRADE-016 T0Task UI 集成（v18）

`T0Trade.vue` MUST 在顶部集成 task 切换：

- **当前 task 下拉**：展示 `active` 状态任务列表（按更新时间倒序）
- **无 task 模式**：默认选 "未指定 task"（下单不带 task_id，仅 user_def='T0'）
- **建任务按钮**：打开 `<T0TaskCreateDialog>`，从 `usePositionStore().positions` 选 stock_code → 弹输入 `base_volume / target_volume / note`
- **任务详情抽屉**：点击 task 行 → 打开 `<T0TaskDetail>` 抽屉：
  - 顶部：摘要卡片（净敞口 / 已实现 / 未实现 / 胜率 / 累计天数）
  - 中部：每日 PnL 折线图（用现有 `<T0ChartGeometry>` / ECharts）
  - 下部：操作按钮 `[一键配平] [关任务] [编辑]`
- **下单带 task_id**：`useT0OrderSubmit.submitOrder(...)` MUST 在选了 task 时附带 `task_id`

#### Scenario: 未选 task 下单

- **WHEN** 用户当前下拉 = "未指定 task"
- **AND** 提交买单 `{ stock_code: '600519.SH', volume: 100, price: 15 }`
- **THEN** 后端收到 `Order{user_def='T0', task_id=NULL}`
- **AND** 与 v17 行为完全一致（向后兼容）

#### Scenario: 选 task 下单

- **WHEN** 用户当前下拉 = task id=5
- **AND** 提交买单
- **THEN** 后端收到 `Order{user_def='T0', task_id=5}`

#### Scenario: 任务详情抽屉

- **WHEN** 点击 task 行
- **THEN** 抽屉滑入，宽度 480px
- **AND** 加载 `/api/t0-tasks/{id}/stats` 显示摘要 + 每日 pnl 图表
- **AND** 失败重试 1 次后弹 ElMessage.error

#### Scenario: 建任务对话框

- **WHEN** 用户点 `[+ 新建任务]` → 选 stock `002594.SH`
- **AND** 提交 `{ base_volume: 0, target_volume: 1000, note: '测试建任务' }`
- **THEN** 后端 `POST /api/t0-tasks` 返回 `{id: 6, ...}`
- **AND** 前端下拉自动切换到新 task
- **AND** 弹 ElMessage.success "任务创建成功"

### Requirement: REQ-TRADE-017 T0Task 跨日配平语义（v18）

"跨多日也能迅速配平" 的核心是 task 净敞口跨日累加：

- **Task 净敞口定义**：`task_net_volume = Σ(buy_vol) - Σ(sell_vol)` for orders where `task_id=X` AND `trd_date IN (created_trd_date, today]`
- **配平缺口公式**：
  ```
  position_vol = Position{stock_code}.vol（当前全部持仓，含 task 外底仓）
  target_position = base_volume + target_volume
  gap = target_position - position_vol
  balance_volume = round_to_lot(gap * coefficient)
  ```
- **正向 gap**（target > current）→ 提交买单
- **负向 gap**（target < current）→ 提交卖单
- **跨日累加**：每次配平提交的单都归到 task 下，下次配平时已计入

#### Scenario: 跨日累加净敞口

- **GIVEN** task `id=5, base_volume=1000, target_volume=2000, status='active'`
- **AND** T1 成交 `buy=500, sell=0` → `task_net_volume=500`
- **AND** T2 成交 `buy=0, sell=200` → `task_net_volume=300`
- **AND** T3 当前 `Position.vol=1300`（含 task 外 1000）
- **WHEN** `POST /api/t0-tasks/5/balance`
- **THEN** `position_vol=1300, target_position=3000, gap=+1700`
- **AND** 提交买单 `volume=round_to_lot(1700, 'BUY')=1700`（A 股整手）

#### Scenario: 配平保留底仓

- **GIVEN** task `id=5, base_volume=1000, target_volume=0, status='active'`
- **AND** 当前 `Position.vol=2000`（1500 task 内买 + 500 task 外 + 1000 base 不动）
- **WHEN** `POST /api/t0-tasks/5/balance { auto_close: false }`
- **THEN** `target_position = 1000 + 0 = 1000`
- **AND** `gap = 1000 - 2000 = -1000`
- **AND** 提交卖单 `volume=round_to_lot(1000, 'SELL')=1000`
- **AND** 配平后 `Position.vol=1000` = **底仓被保留**

#### Scenario: 跨多日 task 自动续命

- **GIVEN** task 创建于 T1，跨 T1/T2/T3/T4 共 4 个交易日
- **WHEN** 跨 4 日仍未关
- **THEN** 状态保持 `active`，`last_trd_date` 自动更新
- **AND** `trading_days = 4`（统计累计天数）

### Requirement: REQ-TRADE-018 整体做 T 收益 + 单券做 T 收益视图（v18）

新组件 `<T0TaskOverview>` 展示两层收益：

- **整体做T收益（cross-task summary）**：
  - 数据：`/api/t0-tasks?status=active` + `/api/t0-tasks?status=closed&days=30` 聚合
  - 卡片：累计 realized_pnl / 未实现 pnl / 总手续费 / 总印花税 / 累计天数 / 总胜率 / 活跃 task 数
- **单券做T收益（per-stock summary）**：
  - 数据：服务端聚合 `SELECT stock_code, SUM(realized_pnl), SUM(unrealized_pnl) ... GROUP BY stock_code` 走 task 维度
  - 卡片：每只券一行（stock_code / 已实现 / 未实现 / 净敞口 / task 数 / 累计天数）

#### Scenario: 整体视图

- **WHEN** 用户访问 `/t0-trade` 顶部
- **THEN** 显示 5 个 metric pill（沿用 REQ-TRADE-013 quota frame 风格）：
  - 累计已实现 = SUM(task.realized_pnl) for all tasks (active + closed last 30d)
  - 累计未实现 = SUM(task.unrealized_pnl) for active tasks
  - 活跃 task 数 = COUNT(where status='active')
  - 累计手续费 = SUM(task.commission_total) for closed last 30d
  - 胜率 = AVG(task.win_rate) for closed last 30d

#### Scenario: 单券视图

- **WHEN** 用户切到 "单券视角"
- **THEN** 列出所有有 task 的 stock_code：
  ```
  600519.SH  累计¥1200  未实现¥350  净+700  3 task  6日
  002594.SH  累计¥-200  未实现¥0    净 0    1 task  2日
  ...
  ```
- **AND** 点击行 → 跳到该 stock_code 的 task 列表

#### Scenario: 兼容旧 user_def='T0' 视角

- **WHEN** 用户没有建任何 task，但有 user_def='T0' 的旧单
- **THEN** `<T0TaskOverview>` 显示 "暂无 task，但有 X 笔历史 T0 单"
- **AND** 给出 "导入为 task" 按钮 → 把旧单按 stock_code 分组建 task