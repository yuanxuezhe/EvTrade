# XtQuant QMT RPC 接口契约

> 权威源: [iquant/xtquant_api.py](../iquant/xtquant_api.py)
> 消息协议: msgpacket (`MSG_TYPE_ANSWER` 应答 / `MSG_TYPE_PUSH` 推送)
> 传输: RabbitMQ Topic Exchange (`msgpacket.exchange`)
> - 请求队列: `EvTrade.Test.Req`
> - 应答队列: `EvTrade.Test.Reply`
> - 推送队列: `EvTrade.Test.Push`

## 1. 协议约定

### 1.1 应答包结构（RS1 + RS2）

每个应答包由 **2 个结果集 (ResultSet)** 组成：

**RS1 — 状态行**（固定 2 列）

| 列 | 类型 | 含义 |
|---|---|---|
| `code` | str | `"00000"` 成功 / `"99999"` 失败 |
| `msg`  | str | 描述文本 |

**RS2 — 数据表**（仅 `code == "00000"` 且有数据时存在）

列名与各接口的"返回字段表"一致。每行一条记录。

### 1.2 请求包结构

每个请求包：

- `func`: 函数名（见 §2 接口列表）
- `headers`: 列名（逗号分隔，与 RS2 一致）
- `values`: 字段值 dict

### 1.3 推送包结构

由 [iquant/xtquant_api.py:312-343](../iquant/xtquant_api.py#L312-L343) 的 `push_event()` 发布：

- `type=MSG_TYPE_PUSH`
- `func`: 推送类型（见 §3 推送列表）
- 单个 RS1 结果集即为数据行

---

## 2. RPC 接口列表

### 2.1 qry_pos — 查询持仓

**方向**: server → broker
**返回**: 持仓列表

**请求**：`func="qry_pos"`，无 values（broker 固定查本账户）

**响应 RS2 字段**（[iquant/xtquant_api.py:108-117](../iquant/xtquant_api.py#L108-L117)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `stock_code` | str | 证券代码 |
| `volume`     | int | 总持仓 |
| `avl_amt`    | int | 可用数量 |
| `avg_price`  | float | 持仓成本价 |
| `market_value` | float | 持仓市值 |

> **v10 字段名约定**: 不再 alias 为 `available` / `cost`，保留 broker 原字段名。
> 权威源: [server/rpc/parsers_business.py:103-119](../server/rpc/parsers_business.py#L103-L119)

### 2.2 qry_ord — 查询委托

**方向**: server → broker
**返回**: 当日全部委托

**请求**：`func="qry_ord"`，无 values

**响应 RS2 字段**（[iquant/xtquant_api.py:120-136](../iquant/xtquant_api.py#L120-L136)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `order_id` | str | 柜台委托号 |
| `stock_code` | str | 证券代码 |
| `price` | float | 委托价 |
| `order_volume` | int | 委托量 |
| `traded_volume` | int | 已成交量 |
| `traded_price` | float | 成交均价 |
| `order_status` | str | 状态码（48/49/50/51/52/53/55） |
| `status_msg` | str | 状态描述 |
| `strategy_name` | str | 策略名 |
| `order_remark` | str | 委托备注（透传本地下单的 `order_no`） |
| `order_time` | str | 委托时间（紧凑格式 YYYYMMDDHHMMSSfff） |

> v10 起直接读 broker 原 `order_status` / `order_volume`，不再 alias。

### 2.3 qry_ast — 查询资金

**方向**: server → broker
**返回**: 单行资金数据

**请求**：`func="qry_ast"`，无 values

**响应 RS2 字段**（[iquant/xtquant_api.py:139-151](../iquant/xtquant_api.py#L139-L151)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `account_id` | str | 账号 |
| `cash` | float | 现金 |
| `frozen_cash` | float | 冻结资金 |
| `market_value` | float | 持仓市值 |
| `total_asset` | float | 总资产 |

### 2.4 qry_mch — 查询成交

**方向**: server → broker
**返回**: 当日全部成交

**请求**：`func="qry_mch"`，无 values

**响应 RS2 字段**（[iquant/xtquant_api.py:154-168](../iquant/xtquant_api.py#L154-L168)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `order_id` | str | 关联委托号 |
| `traded_id` | str | 成交编号（**UNIQUE 去重键**） |
| `stock_code` | str | 证券代码 |
| `traded_volume` | int | 成交量 |
| `traded_price` | float | 成交价 |
| `traded_amount` | float | 成交额 |
| `strategy_name` | str | 策略名 |
| `order_remark` | str | 委托备注（=本地 order_no） |
| `traded_time` | str | 成交时间（紧凑格式） |

### 2.5 ord_stk — 下单

**方向**: server → broker
**同步返回**: 柜台 ack（seq / order_id）
**异步推送**: ord_cfm / trd_cfm 通过 `EvTrade.Test.Push` 到达

**请求 headers**: `stock_code,volume,price_type,price,direction,remark`

**请求 values**（[iquant/xtquant_api.py:175-193](../iquant/xtquant_api.py#L175-L193)）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock_code` | str | ✓ | 证券代码 |
| `volume` | int | ✓ | 委托量 |
| `price_type` | str | ✓ | `"0"` 限价 / `"1"` 最新价 |
| `price` | float | ✓ | 委托价（限价时） |
| `direction` | str | ✓ | `"BUY"` / `"SELL"` |
| `remark` | str | ✓ | 委托备注（**透传本地的 `order_no`**，broker 在 ord_cfm 中回带） |

**响应 RS2 字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | int | 柜台异步下单序号（v8+ 不再用，仅占位） |

### 2.6 cxl_ord — 撤单

**方向**: server → broker

**请求 headers**: `order_id,market`

**请求 values**（[iquant/xtquant_api.py:196-203](../iquant/xtquant_api.py#L196-L203)）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `order_id` | str | ✓ | 柜台委托号（**不是**本地 `order_no`） |
| `market` | str | ✓ | `"SH"` / `"SZ"` |

**响应 RS2 字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `result` | int | 柜台返回码（非 0 即失败） |

---

## 3. 推送列表（broker → server）

由柜台回调 → [iquant/xtquant_api.py:244-305](../iquant/xtquant_api.py#L244-L305) → RabbitMQ Push 队列。

每条 push 是**单条数据**（不是数组）。字段名 v10 保持 broker 原字段名。

### 3.1 ord_cfm — 委托确认

**触发**: `XtQuantTraderCallback.on_stock_order`

**字段**（[iquant/xtquant_api.py:252-265](../iquant/xtquant_api.py#L252-L265)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `order_id` | str | 柜台委托号 |
| `stock_code` | str | 证券代码 |
| `order_status` | str | 48/49/50/51/52/53/55 |
| `order_volume` | int | 委托量（broker 改单后真实数） |
| `traded_volume` | int | 已成交量 |
| `price` | float | 委托价 |
| `traded_price` | float | 成交均价 |
| `strategy_name` | str | 策略名 |
| `remark` | str | = 本地 `order_no`（**关键匹配键**） |
| `order_time` | str | 标准时间 |

> **server 侧消费**: [server/services/push/ord.py:33-92](../server/services/push/ord.py) 用 `remark` 匹配本地 `Order` 行

### 3.2 trd_cfm — 成交回报

**触发**: `XtQuantTraderCallback.on_stock_trade`

**字段**（[iquant/xtquant_api.py:267-277](../iquant/xtquant_api.py#L267-L277)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `traded_id` | str | 成交编号（**Trade PK 第三段**） |
| `stock_code` | str | 证券代码 |
| `traded_volume` | int | 成交量 |
| `traded_price` | float | 成交价 |
| `account_id` | str | 账号 |
| `strategy_name` | str | 策略名 |
| `remark` | str | = 本地 `order_no`（**关键匹配键**） |

> 缺少 `traded_amount` / `traded_time` 字段（broker 未在 callback 中暴露）— 由 server 端 `Trade.amount = price * volume` 计算，`trade_time` 用 push 包的 `ts`（权威源: [server/rpc/transport.py:272](../server/rpc/transport.py#L272)）

### 3.3 ord_err — 下单失败

**触发**: `XtQuantTraderCallback.on_order_error`

**字段**:

| 字段 | 类型 | 说明 |
|---|---|---|
| `order_id` | str | 柜台委托号 |
| `error_msg` | str | 错误描述 |

### 3.4 cxl_err — 撤单失败

**触发**: `XtQuantTraderCallback.on_cancel_error`

**字段**:

| 字段 | 类型 | 说明 |
|---|---|---|
| `order_id` | str | 柜台委托号 |
| `error_msg` | str | 错误描述 |

### 3.5 ord_ack — 异步下单应答

**触发**: `XtQuantTraderCallback.on_order_stock_async_response`

**字段**:

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | int | 柜台异步下单序号 |
| `order_id` | str | 柜台委托号 |

### 3.6 acc_sts — 账号状态

**触发**: `XtQuantTraderCallback.on_account_status`

**字段**:

| 字段 | 类型 | 说明 |
|---|---|---|
| `account_id` | str | 账号 |
| `status` | int | 状态码（broker 自定义） |

---

## 4. server → broker 的 RPC 调用

server 侧通过 [server/rpc/handlers.py](../server/rpc/handlers.py) 封装调用：

| Python 函数 | RPC func | 用途 |
|---|---|---|
| `qry_asset()`    | `qry_ast` | 资金查询（日初对账用） |
| `qry_orders()`   | `qry_ord` | 委托查询（日初对账用） |
| `qry_trades()`   | `qry_mch` | 成交查询（日初对账用） |
| `qry_positions()`| `qry_pos` | 持仓查询（日初对账用） |
| `ord_stk(...)`   | `ord_stk` | 下单（[server/api/orders/place.py:84](../server/api/orders/place.py#L84) 调用） |
| `cancel_order(...)` | `cxl_ord` | 撤单（[server/api/orders/cancel.py:91](../server/api/orders/cancel.py#L91) 调用） |

> **v4 改造后**: 业务查询接口（[server/api/positions.py](../server/api/positions.py) / [server/api/asset.py](../server/api/asset.py) / [server/api/orders/query.py](../server/api/orders/query.py)）**不再调 RPC**，只读本地 DB。RPC 只用于下单/撤单/日初对账。
> 权威源: [openspec/AGENTS.md](../openspec/AGENTS.md) "约定" §数据源
