## ADDED Requirements

### Requirement: 前端独立计算委托 / 成交缓存（REQ-FE-009.9）

The system SHALL 在 holdings store 缓存层独立维护委托 / 成交的累计字段，**不读 ws 推送 payload 的累积 / cancelled_volume / status 字段**。ws 推送的 trd_cfm payload 仅含当前笔 trade 字段，holdings store 通过单笔 trade 增量累计到对应 order 行。

具体规则：

- **`trades.amount`**：本地 `price × volume` 计算，不引用 ws payload 的 amount 字段
- **`orders.traded_volume`**：各 trd_cfm 单笔 `volume` 在对应 `order_no` 上增量累加
- **`orders.traded_amount`**：各 trd_cfm 单笔 `price × volume` 在对应 `order_no` 上增量累加
- **`orders.avg_price`**：`traded_amount / traded_volume`，防 `traded_volume == 0` 除零
- **`orders.status`**：调 `inferOrderStatus(order, null)` 本地推断（不传 brokerStatus），与后端 `_infer_order_status` 镜像
- **`orders.cancelled_volume`**：
  - bootstrap / refresh 拉取时：接受 row 字段作为初始值
  - 运行时：cancel-row ws 推送（`order_flag === 1`）按 `user_def = 'CANCEL:{orig_order_no}'` 反向定位原委托，把 `orig.cancelled_volume = orig.volume` 一次性抹平

ws 推送的 `order_update` payload SHALL 仅用于 PK + 元数据覆盖（`order_id / user_def / order_time / stock_code / order_type / price_type / price / volume / status_msg`），MUST NOT 覆盖 `traded_volume / traded_amount / avg_price / cancelled_volume / status` 等本地维护字段。

bootstrap 与 refresh 路径（`/api/orders` 与 `/api/trades` 拉取响应）SHALL 接受 row 累计字段作为初始值，再重算 `avg_price / status / cancelled_volume`。

Vue ref 响应式 SHALL 支持实时 UI 渲染：所有改动通过 `value[idx] = newObj` 触发，holdings store 的 ref 数组自动触发 `<el-table>` 等 watcher。

#### Scenario: trd_cfm 推送增量累计

- **WHEN** ws 收到 broker 推来的 trd_cfm payload（携带 trade_id / order_no / price / volume / stock_code / trade_time 等单笔字段）
- **THEN** trades.value 按 trade_id 去重 unshift（amount = price × volume）；找到 orders.value 中匹配 order_no 的行后增量累加 traded_volume += trade.volume、traded_amount += trade.price × trade.volume、avg_price = traded_amount / traded_volume；调 inferOrderStatus 推断 status

#### Scenario: order_update 推送只读 PK + 元数据

- **WHEN** ws 收到 broker ord_cfm 推来的 order_update payload
- **THEN** 在 applyOrderPush 内 ref 计算字段（traded_volume / traded_amount / avg_price / cancelled_volume / status）原值保留；仅覆盖 order_id / user_def / order_time / stock_code / order_type / price_type / price / volume / status_msg 等元数据

#### Scenario: cancel-row 推送反向抹平原委托

- **WHEN** ws 收到 order_flag === 1 的 cancel-row order_update 推送
- **THEN** applyOrderPush 内：写入 cancel-row 自身到 orders.value（按 order_no 去重）；按 row.user_def 解析出 orig_order_no（用户开头 'CANCEL:'）；在 orders.value 中找到对应原委托行，把 orig.cancelled_volume 抹平为 orig.volume

#### Scenario: bootstrap / refresh 拉取响应作为初始值

- **WHEN** `GET /api/orders` 拉取响应作为 bootstrap / refreshAll 入口
- **THEN** orders.value 接受 row.traded_volume / row.traded_amount / row.cancelled_volume 作为初始值；重算 avg_price = traded_amount / traded_volume 与 status = inferOrderStatus(order, null)；trades.value 接受 row 字段，amount 重算为 price × volume

#### Scenario: 推送 payload 缺 amount 字段

- **WHEN** broker 协议老版本 trd_cfm 行不携带 amount 字段
- **THEN** holdings.applyTradePush 仍按本地 `price × volume` 写入 trades.amount；不抛错

#### Scenario: trd_cfm 推送对应 order 在 ref 中不存在

- **WHEN** ws 收到 broker trd_cfm 行 order_no 在 orders.value 中未找到对应行
- **THEN** trades 仍按 trade_id 去重 unshift；不抛错；下次 trd_cfm / bootstrap 拉取时校正

#### Scenario: 实时 UI 渲染

- **WHEN** holdings store 任一 `value[idx] = newObj` / `value[idx].field = value` 改动
- **THEN** Vue ref reactivity 在下一个 microtask 自动通知 watcher；<el-table> 列展示（如已成 / 已撤 / 状态）即时刷新

### Requirement: 前端 helper 工具函数与后端镜像（REQ-FE-009.9.1）

The system SHALL 在 `client/src/utils/orderCalc.js` 提供：

- `normalizeTrade(trade)`：返回 `{...trade, amount: price × volume}`
- `recomputeOrderFromTrade(order, trade)`：返回基于单笔 trade 增量累计的新 order 对象（含 status 推断）
- `metaMerge(row, ref)`：返回仅覆盖 PK + 元数据、保留 ref 计算字段的合并结果
- `flattenCancelledByRow(row, orders)`：cancel-row 触发的反向抹平逻辑，返回 orders 中被影响的下标与新值

helper 函数 MUST 与后端 `_order_to_out_dict / handle_trd_cfm / cancel.py / place.py` 等写入路径字段语义逐字对齐。

#### Scenario: helper 调用

- **WHEN** `applyTradePush(row)` 收到 broker trd_cfm 单笔 trade
- **THEN** 内部调 `recomputeOrderFromTrade(orderRef, row)` 计算新 order，与 `inferOrderStatus` 一并更新 ref

#### Scenario: helper 单测覆盖

- **WHEN** 单测 fixture input `{price: 12.5, volume: 200}`
- **THEN** `normalizeTrade(trade).amount === 2500`
- **WHEN** 单测 fixture order `{volume: 100, traded_volume: 30, traded_amount: 3000, cancelled_volume: 0}` + trade `{price: 12.5, volume: 50}`
- **THEN** `recomputeOrderFromTrade(order, trade).traded_volume === 80`、`.traded_amount === 3625`、`.avg_price === 45.3125`
