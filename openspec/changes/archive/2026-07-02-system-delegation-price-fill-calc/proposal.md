## Why

委托 / 成交的"价格 / 成交均价 / 成交金额 / 撤单数量"计算当前分散在 5 个写入路径上，口径不统一：
- `trades.amount` 在 broker 推送路径信 `broker.traded_amount` 字段，与 data-model spec「成交额 = price × volume」声明不一致
- `orders.avg_price` 在 trd_cfm 累加路径有 `if trade.price and trade.volume:` 守卫，broker 异常笔下会出现累计均价语义漂移
- `orders.cancelled_volume` 写入路径依赖 broker 推字段兜底，**本地**没有任何"撤单成功 / 废单"抹平规则，与 DELETE 端点的本地代理行 (`order_flag=1`) 没有收尾
- 前端 ws 推送合并是 `{ ...ref, ...row }` spread，对服务端 broadcast payload 字段缺失 / broker 重发陈旧包等时序不变量无保护，可能出现从大值退回小值的覆盖 race

本 change 把"前后端算法对齐 + 前端独立累计"作为单一口径收齐，避免双源飘逸。

## What Changes

**后端 — 4 处代码修改**

- `server/services/push/trd.py`：`trades.amount` 改本地算 `price × volume`，丢弃 broker 的 `traded_amount` 字段；`orders.avg_price` 守卫简化为仅防 `traded_volume == 0` 除零
- `server/api/orders/cancel.py`：撤单成功（`ack.code == 0`）时把原委托 `cancelled_volume` 一次性抹平为 `volume`（**R1**）
- `server/api/orders/place.py`：`ack.code != 0` 写 `status=55` 时把 `cancelled_volume` 抹平为 `volume`（**R2a 本地拒单**）
- `server/services/push/ord.py`：broker ord_cfm 推回拒单类 status 且未推 `cancelled_volume` 时本地兜底抹平（**R2b broker 推回废单**）

**前端 — 1 新建 + 3 改动 + 2 新增 helper**

- 新建 `client/src/utils/orderCalc.js`：集中 `normalizeTrade` 与 `normalizeOrder` 工具，与后端 helper 字段语义对齐（不含服务器侧持久化语义，纯客户端累计）
- `client/src/stores/holdings_helpers.js`：re-export `normalizeTrade / normalizeOrder`
- `client/src/stores/holdings_push.js`：
  - `applyTradePush(row)`：**前端独立累计**——按 `trade_id` 去重写入 `trades`，反向定位 `order_no` 对应行后增量累加 `traded_volume / traded_amount / avg_price`，最后调 `inferOrderStatus` 推断 status
  - `applyOrderPush(row)`：**只读 PK + 元数据**——不读 row 的 `status / traded_volume / traded_amount / avg_price / cancelled_volume`，保留 ref 字段不动；`order_flag=1` 的 cancel-row 在 spread 写入后由 `user_def='CANCEL:{orig_order_no}'` 反向定位原委托，把 `orig.cancelled_volume = orig.volume` 抹平
- `client/src/stores/holdings_apply_results.js`：4 个 `applyOrders* / applyTrades*` 入口对每条 row 跑本地 normalize（**bootstrap / refresh** 时用 row 累计字段作初始值，再重算 `status / avg_price / cancelled_volume`）

**Spec 层 — 2 处修改**

- `openspec/specs/data-model/spec.md`：
  - §1 `orders.cancelled_volume` 注释补写「撤单成功 / 本地拒单 / broker 推回废单类兜底三种触发一次性抹平到 volume」与「DELETE 失败不动」
  - §2 `trades.amount` 改写为「成交额 = price × volume（本地算，不采用 broker 推送的 traded_amount）」
- `openspec/specs/frontend/spec.md`：新增 **REQ-FE-009.9 前端独立计算委托/成交缓存**——声明 ws 推送的 trd_cfm payload 只含当前笔字段，前端按 trade_id 去重，按 order_no 反向增量累计 `traded_volume / traded_amount / avg_price`，status 走 `inferOrderStatus` 本地推断；ws 推送的 order_update payload 只读 PK + 元数据，不信 `status / 累计 / cancelled_volume` 字段；cancel-row 由前端按 `user_def` 反向定位原委托抹平 cancelled_volume

**测试层 — 6 类回归**

- 后端 4 类（broker 推怪异 traded_amount 时不入表 / 撤单成功后 cancelled=volume / place.py 拒单后 cancelled=volume / DELETE 失败后 cancelled 不动）
- 前端 2 类（normalizeTrade 单测 / normalizeOrder 单测——`status ∈ {53,54,55,56}` 抹平 / `inferOrderStatus` 时序 race）
- 历史 trades 表 amount 与 `price × volume` 关系做一次 dry-run 回填评估脚本

## Capabilities

### New Capabilities
无

### Modified Capabilities
- `data-model`：`orders.cancelled_volume` 与 `trades.amount` 写入语义明确为本地算口径
- `frontend`：新增 REQ-FE-009.9 段——前端独立计算委托/成交缓存（ws payload 字段约定 + 取舍规则）

## Impact

- **代码**：
  - 后端 4 处单点修改（`push/trd.py` / `api/orders/cancel.py` / `api/orders/place.py` / `push/ord.py`）
  - 前端 1 新建 + 3 改动（`utils/orderCalc.js` / `stores/holdings_helpers.js` / `stores/holdings_push.js` / `stores/holdings_apply_results.js`）
- **数据库**：列定义无变化
- **API**：现有 schema 不变；ws broadcast 字段语义受影响（详见前段点对点说明）
- **下游影响**：
  - `cancel.py` 的 cancel-row `order_flag=1` payload 与前端 `user_def='CANCEL:{orig_order_no}'` 反向抹平之间的契约首次进入 spec
  - trd_cfm 本地算 `amount = price × volume` 后，broker 在 `traded_amount` 字段推送的值不再被采纳；如有历史 data 不一致，需做一次 dry-run 回填
  - 任何新增对 `trades.amount` / `orders.traded_amount / avg_price / cancelled_volume` 的写入路径（如 reconcile 后的反向回写）必须走本 change 规定的统一口径
- **回归测试**：原 `tests/server/api/orders/*` 与 `tests/server/services/push/test_handlers.py` 必须仍通过；新增测试不破坏现有 11 个 trd_cfm 用例
