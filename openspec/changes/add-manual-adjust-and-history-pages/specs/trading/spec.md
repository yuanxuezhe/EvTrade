## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: today / history 视图拆分（v12）

`client/src/views/Orders.vue` 与 `Trades.vue` MUST 被拆分为 4 个独立 view + 4 个独立路由：

| 旧路由 | 新路由拆分 |
|---|---|
| `/orders`（混合当日+历史） | `/today/orders` + `/history/orders` |
| `/trades`（混合当日+历史） | `/today/trades` + `/history/trades` |

详见 `intraday-orders-trades-cache/spec.md` 与 `orders-trades-history-query/spec.md`。
