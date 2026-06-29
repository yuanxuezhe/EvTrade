# Server REST API 契约

> 权威源: [server/api/](../server/api/) + [server/main.py](../server/main.py) 的 include_router
> 基础 URL: `http://<host>:8000/api`
> 鉴权: 除 `POST /api/auth/login` 外，所有端点需 `Authorization: Bearer <JWT>`
> 通用响应格式: `{code: int, msg: str, list: [...]}`

## 0. 通用约定

### 0.1 鉴权角色矩阵

| 端点前缀 | viewer | trader | admin |
|---|:---:|:---:|:---:|
| `/api/auth/*` | — | — | — |
| `/api/users` | ✗ | ✗ | ✓ |
| `/api/orders/place` | ✗ | ✓ | ✓ |
| `/api/orders/{order_no}` (DELETE) | ✗ | ✓ | ✓ |
| `/api/fee-config` (PATCH) | ✗ | ✗ | ✓ |
| `/api/admin/*` | ✗ | ✗ | ✓ |
| 其他 | ✓ | ✓ | ✓ |

`require_trading_day` / `require_trading_session` 屏障（[server/services/guards.py](../server/services/guards.py)）适用：
- 下单/撤单端点要求已激活交易日 + 交易时段内
- 查询端点不受限

### 0.2 时间格式

v10 统一为 `"YYYY-MM-DD HH:MM:SS.fff"`（[server/utils/time.py](../server/utils/time.py) `format_db_dt`）

### 0.3 标准 RPC 响应

```json
{ "code": 0, "msg": "", "list": [ ... ] }
```

`code != 0` 时 `list` 为空。axios 拦截器自动展平 `res.data = list`（[openspec/AGENTS.md §约定](../openspec/AGENTS.md)）。

---

## 1. 鉴权 `/api/auth/*`

### 1.1 POST `/auth/login`

**请求**（OAuth2 form）:
- `username` (form)
- `password` (form)

**响应** `TokenResponse`:

| 字段 | 类型 | 说明 |
|---|---|---|
| `access_token` | str | JWT |
| `token_type` | str | 固定 `"bearer"` |
| `expires_in` | int | 秒数（24h = 86400） |
| `user` | object | `{id, username, email, full_name, role, is_active, must_change_password, created_at, last_login_at}` |

**错误**: 401 用户名密码错 / 403 账号禁用

> 权威源: [server/api/auth.py:48-77](../server/api/auth.py#L48-L77)

### 1.2 GET `/auth/me`

**响应** `UserInfoResponse`

> 权威源: [server/api/auth.py:80-82](../server/api/auth.py#L80-L82)

### 1.3 PATCH `/auth/me`

**请求** `UpdateProfileRequest`: `{email?, full_name?}`

### 1.4 POST `/auth/change-password`

**请求** `ChangePasswordRequest`: `{old_password, new_password}`
- `new_password` ≥ 6 位
- `new_password != old_password`

### 1.5 POST `/auth/logout`

**响应**: `{success: true}` — 无状态 JWT，客户端丢弃 token 即可；端点保留用于审计

---

## 2. 用户管理 `/api/users/*`（admin only）

### 2.1 GET `/users?keyword=&role=`

**响应**: `List[UserResponse]`

### 2.2 POST `/users`

**请求** `UserCreateRequest`: `{username, password, role?, email?, full_name?, is_active?}`
- `username`: 3-32 位字母/数字/`_`/`-`/`.`
- `password`: ≥ 6 位
- `role`: `admin` / `trader` / `viewer`（默认 `trader`）

**错误**: 409 用户名已存在 / 400 校验失败

### 2.3 PATCH `/users/{user_id}`

**请求** `UserUpdateRequest`: `{role?, email?, full_name?, is_active?}`
- 不可降级最后一个 admin
- 不可禁用当前登录账号

### 2.4 POST `/users/{user_id}/reset-password`

**请求**: `{new_password}`

### 2.5 DELETE `/users/{user_id}`

- 不可删除当前登录账号
- 不可删除最后一个 admin

> 权威源: [server/api/users.py](../server/api/users.py)

---

## 3. 委托 `/api/orders/*`

### 3.1 POST `/orders/place`（trader only）

**请求** `PlaceOrderRequest`（[server/api/orders/schemas.py:25-33](../server/api/orders/schemas.py#L25-L33)）:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_def` | str | ✗ | 外部自定义信息（透传，**默认空串**） |
| `stock_code` | str | ✓ | 证券代码 |
| `order_type` | str | ✓ | `"23"` 买 / `"24"` 卖 |
| `price_type` | int | ✗ | 默认 `PriceType.LIMIT` (限价) |
| `price` | float | ✓ | 委托价 |
| `volume` | int | ✓ | 委托量 |
| `t0_coefficient` | float | ✗ | T0 配平系数，默认 `1.0` |

**响应** `PlaceOrderResponse`（[server/api/orders/schemas.py:53-61](../server/api/orders/schemas.py#L53-L61)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | int | 0=成功 |
| `msg` | str | 状态消息 |
| `order` | OrderOut | 委托详情（v8 兼容字段） |
| `list` | List[OrderOut] | 1 行（v8 统一 RPC 格式） |
| `broker_order_id` | str | 柜台委托号（broker 回报后写入） |
| `fee_breakdown` | object | `{gross, net, commission_rate}` |
| `t0_adjusted_volume` | int | T0 配平后实际委托量 |
| `error` | str | 错误详情（仅失败时） |

**`OrderOut` 字段**（[server/api/orders/schemas.py:36-51](../server/api/orders/schemas.py#L36-L51)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `order_id` | str | 柜台委托号（**broker 未回报前为空串**） |
| `user_def` | str | 透传（v7+） |
| `order_no` | str | 本地 8 位数字（DB 序列表原子生成） |
| `trd_date` | str | YYYYMMDD |
| `stock_code` | str | |
| `order_type` | str | 23/24 |
| `price_type` | int | |
| `price` | float | |
| `volume` | int | |
| `traded_volume` | int | |
| `traded_amount` | float | |
| `avg_price` | float | |
| `cancelled_volume` | int | 累计撤单量（v8+） |
| `order_flag` | int | 0=normal / 1=cancel-order（v9+） |
| `status` | str | 48/49/50/51/52/53/55 |
| `status_msg` | str | |
| `order_time` | str | YYYY-MM-DD HH:MM:SS.fff |

**错误**: 400 (BAD_ORDER_TYPE / VOLUME_TOO_SMALL) / 503 (未做日初 / 非交易时段)

> 权威源: [server/api/orders/place.py](../server/api/orders/place.py)

### 3.2 DELETE `/orders/{order_no}?trd_date=YYYYMMDD`（trader only）

**请求 query**:
- `trd_date` (必填): 8 位数字

**响应** `CancelResponse`（[server/api/orders/schemas.py:73-79](../server/api/orders/schemas.py#L73-L79)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | int | 0=撤单成功 |
| `msg` | str | |
| `order_id` | str | 原委托的 broker order_id |
| `cancel_ack` | object | 柜台撤单 ack 原始结构 |
| `cancel_order` | OrderOut | **本地代理的撤单委托行**（status=53 已撤 / 55 废单） |
| `error` | str | 失败原因 |

**Pre-checks 触发即返回**:
- status ∉ {48, 49} → `code=1, msg="当前 status=X 不可撤"`
- broker 尚未回报 order_id → `code=1, error="BROKER_NOT_READY"`

**架构说明**: 柜台 cancel_ord 只接 `order_id`，不接 `order_no`，且 `ord_cfm.remark` 永远回带**原** order_no。cancel-row 是**纯本地**，由本端点 INSERT 一行 `order_flag=1` 的 Order；成功后由端点**手动推** `order_update` 给前端（broker 不会推这一行）。权威源: [server/api/orders/cancel.py:1-10](../server/api/orders/cancel.py#L1-L10)

### 3.3 GET `/orders?stock_code=&status=&trd_date=&limit=&offset=`

**Query**:
- `trd_date` 缺省 = 激活日
- `limit` ≤ 500（默认 100）
- `offset` 默认 0

**响应** `ListOrdersResponse`: `{code, msg, list: [OrderOut, ...], total}`

> 权威源: [server/api/orders/query.py:30-58](../server/api/orders/query.py#L30-L58)

### 3.4 GET `/orders/history?trd_date=&stock_code=&status=&limit=`

**Query**:
- `trd_date` (必填): 8 位数字
- `limit` ≤ 2000（默认 500）

---

## 4. T0 统计 `/api/orders/*`（扩展）

### 4.1 GET `/orders/t0-stats/{stock_code}?trd_date=&t0_only=`

**响应** `T0StatsOut`（[server/api/t0_stats.py:30-46](../server/api/t0_stats.py#L30-L46)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `trd_date` | str | |
| `stock_code` | str | |
| `today_buy_volume` | int | |
| `today_sell_volume` | int | |
| `today_buy_amount` | float | |
| `today_sell_amount` | float | |
| `realized_pnl` | float | 已实现盈亏（v6 算法：基于持仓成本基准 + 卖出方向费用） |
| `cost_basis` | float | 当前持仓平均成本价 |
| `position_volume` | int | 当前持仓量 |
| `position_cost_total` | float | 持仓成本总额 = `cost_basis * position_volume` |
| `unrealized_pnl` | float | 浮动盈亏（基于当前持仓 × 持仓成本基准） |
| `total_pnl` | float | `realized + unrealized` |
| `order_count` | int | |
| `trade_count` | int | |
| `open_order_count` | int | status ∈ {48, 49, 50} |

**错误**: 400 (NO_TRADING_DAY) — 无激活日

### 4.2 GET `/orders/t0-history/{stock_code}?days=&t0_only=`

**Query**: `days` ∈ [1, 180]（默认 30）

**响应** `T0HistoryOut`: `{stock_code, days, points: [T0HistoryPoint], total_realized, total_return_rate, win_days, total_days}`

`T0HistoryPoint`: `{trd_date, realized_pnl, sell_amount, buy_amount, trade_count}`

### 4.3 GET `/orders/t0-exposure?user_def=&trd_date=`

**Query**:
- `user_def` 默认 `"T0"`（空串=全部）
- `trd_date` 缺省 = 激活日

**响应** `T0ExposureOut`:
```json
{
  "trd_date": "20260629",
  "user_def": "T0",
  "positions": [{
    "stock_code": "...",
    "buy_volume": 0, "sell_volume": 0, "net_volume": 0,
    "buy_amount": 0.0, "sell_amount": 0.0, "net_amount": 0.0,
    "realized_pnl": 0.0, "commission": 0.0, "stamp_tax": 0.0,
    "order_count": 0, "trade_count": 0, "open_order_count": 0,
    "position_volume": 0, "cost_basis": 0.0
  }, ...],
  "totals": {
    "buy_volume": ..., "sell_volume": ..., "net_volume": ...,
    "buy_amount": ..., "sell_amount": ..., "net_amount": ...,
    "realized_pnl": ...,
    "commission_total": ..., "stamp_tax_total": ...
  }
}
```

> 权威源: [server/api/t0_aggregate.py:104-150](../server/api/t0_aggregate.py#L104-L150)

### 4.4 GET `/orders/t0-aggregate?user_def=&days=`

**Query**: `days` ∈ [1, 365]（默认 30）

**响应** `T0AggregateOut`:
```json
{
  "user_def": "T0",
  "days": 30,
  "summary": {
    "total_realized": 0.0, "total_commission": 0.0, "total_stamp_tax": 0.0,
    "total_buy_amount": 0.0, "total_sell_amount": 0.0,
    "win_days": 0, "total_days": 0,
    "win_rate": 0.0, "return_rate": 0.0,
    "trade_count": 0, "order_count": 0, "stocks_traded": 0
  },
  "by_day": [{ "trd_date": "...", "realized_pnl": 0.0, "buy_amount": 0.0,
               "sell_amount": 0.0, "trade_count": 0, "stock_count": 0,
               "commission": 0.0, "stamp_tax": 0.0, "cum_pnl": 0.0 }, ...],
  "by_stock": [{ "stock_code": "...", "trade_count": 0,
                 "realized_pnl": 0.0, "buy_amount": 0.0, "sell_amount": 0.0 }, ...]
}
```

---

## 5. 持仓 / 资金 / 成交（DB-only，v4 后不调 RPC）

### 5.1 GET `/positions?stock_code=`

**响应** `PositionsListResponse`: `{code, msg, list: [PositionOut]}`

`PositionOut`（[server/api/positions.py:38-48](../server/api/positions.py#L38-L48)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `stock_code` | str | |
| `stock_name` | str | |
| `last_vol` | int | 期初 |
| `today_buy` | int | |
| `today_sell` | int | |
| `avl_vol` | int | 可用 |
| `vol` | int | 总持仓 |
| `cost_price` | float | 成本价 |
| `market_value` | float | **成本市值代理**（=`cost_price * vol`；真实市值前端用 quote store 实时算） |
| `synced_at` | str | YYYY-MM-DD HH:MM:SS.fff |
| `synced_from` | str | 来源（`push_pos_cfm` / 对账） |

### 5.2 GET `/holdings?stock_code=`

**响应** `HoldingsListResponse`: `{code, msg, list: [HoldingItem]}`

精简版（6 列）: `{stock_code, last_vol, vol, avl_vol, cost_price, market_value}`

### 5.3 GET `/asset`

**响应** `AssetResponse`: `{code, msg, list: [AssetOut]}`

`AssetOut`: `{cash, frozen_cash, market_value, total_asset, synced_at, synced_from}`

### 5.4 GET `/trades?stock_code=&trd_date=`

**Query**: `trd_date` 缺省 = 激活日

**响应** `TradesListResponse`: `{code, msg, list: [TradeOut]}`

`TradeOut`（[server/api/trades.py:33-43](../server/api/trades.py#L33-L43)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `trade_id` | str | 成交编号 |
| `trd_date` | str | |
| `order_no` | str | 关联本地委托号 |
| `stock_code` | str | |
| `order_type` | str | 23/24 |
| `price` | float | |
| `volume` | int | |
| `amount` | float | |
| `trade_time` | str | YYYY-MM-DD HH:MM:SS.fff |
| `trade_type` | int | 0=normal / 1=cancel-fill（v9+：本地代理撤单成交行） |

---

## 6. 系统查询

### 6.1 GET `/trading/clock`

**响应**（[server/api/clock.py:23-37](../server/api/clock.py#L23-L37)）:

| 字段 | 类型 | 说明 |
|---|---|---|
| `trading_day` | str/null | 激活交易日 |
| `trading_day_initialized` | bool | |
| `default_trading_day` | str | 缺省查询日 |
| `is_in_session` | bool | |
| `current_time` | str | ISO |
| `session_window` | object | `{morning_start, morning_end, afternoon_start, afternoon_end}` |
| `next_session_start` | str/null | ISO |
| `seconds_until_session` | int | |

> 前端轮询用

### 6.2 GET `/system/active-day`

**响应**（v8+ 标准 RPC 格式，权威源: [server/api/system.py](../server/api/system.py)）:
```json
{ "code": 0, "msg": "", "list": [{"trd_date": "20260629", "status": "active"}] }
// 或未做日初:
{ "code": 0, "msg": "no active trading day", "list": [] }
```

### 6.3 GET `/fee-config`

**响应** `FeeConfigOut`: `{commission_rate, stamp_tax_rate, slippage, updated_at}`

### 6.4 PATCH `/fee-config`（admin only）

**请求** `FeeConfigUpdate`: `{commission_rate?, stamp_tax_rate?, slippage?}`

---

## 7. 管理 `/api/admin/*`（admin only）

### 7.1 交易时段 `/admin/trading-session`

#### 7.1.1 GET `/admin/trading-session`

**响应** `SessionOut`: `{morning_start, morning_end, afternoon_start, afternoon_end, is_half_day, updated_at}`

> `is_half_day` 当前 ORM 无此字段，固定返 `false`（[server/api/admin/session.py:75](../server/api/admin/session.py#L75)）

#### 7.1.2 PATCH `/admin/trading-session`

**请求** `SessionUpdate`: `{morning_start?, morning_end?, afternoon_start?, afternoon_end?, is_half_day?}`
- 时间格式 `HH:MM` 或 `HH:MM:SS`
- `is_half_day` 当前**后端忽略**

### 7.2 系统状态 `/admin/sys-status/*`

> v5 重命名（原 `trading-day`）

#### 7.2.1 POST `/admin/sys-status/init`

**请求** `InitRequest`: `{trd_date: "20260629", mode: "auto"|"manual"}`

**响应** `InitResponse`: `{code, msg, report_id?, applied, trading_day?: SysStatusOut, error?}`

#### 7.2.2 POST `/admin/sys-status/reconcile`

**请求** `ReconcileRequest`: `{trd_date, mode}`

**响应**: 同上，但 `applied=false`（仅生成报告，不切日）

#### 7.2.3 GET `/admin/sys-status?days=90`

**响应**: `List[SysStatusOut]`，按 `trd_date` 倒序

#### 7.2.4 GET `/admin/sys-status/active`

**响应** `SysStatusOut`（无激活日时 `trd_date=""`, `status="none"`）

`SysStatusOut`: `{trd_date, status, activated_at, activated_by}`

### 7.3 对账 `/admin/reconcile/*`

#### 7.3.1 GET `/admin/reconcile/config`

**响应** `ReconcileConfigOut`: `{auto_reconcile: bool, auto_use_broker_data: int, updated_at, updated_by}`

> v8 起 `auto_use_broker_data` 保持 `int`（0/1）不转 bool，因前端 `<el-radio :value="1">` 匹配

#### 7.3.2 PATCH `/admin/reconcile/config`

**请求** `ReconcileConfigUpdate`: `{auto_reconcile?, auto_use_broker_data?}`

#### 7.3.3 GET `/admin/reconcile/reports`

**响应**: `List[ReconcileReportSummary]`，每项 `{created_at, trd_date, mode, rpc_status}`

> 90 天滚动窗口，最多 200 条

#### 7.3.4 GET `/admin/reconcile/reports/{trd_date}/{mode}/{created_at}`

**响应**:
```json
{
  "created_at": "...",
  "trd_date": "20260629",
  "mode": "manual",
  "rpc_status": "ok|error",
  "error_message": "...",
  "created_by": "...",
  "diffs": { "...": "..." }
}
```

> `created_at` 多种格式都接受（ISO with/without ms, with T or space）
