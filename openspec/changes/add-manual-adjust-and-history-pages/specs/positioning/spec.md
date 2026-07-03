## ADDED Requirements

### Requirement: 持仓查询响应字段（v12）

`GET /api/positions` 响应字段 MUST 不再含 `today_buy` / `today_sell`。前端不再消费这俩字段。

#### Scenario: GET /api/positions 响应 schema 变化

- **WHEN** 实施本 change
- **THEN** `PositionOut` Pydantic schema 不再有 `today_buy` / `today_sell`
- **AND** 前端 `useHoldingsStore().positions` 数组元素不含这俩字段
- **AND** `client/src/stores/holdings_market.js:createMarketComputeds` 不会去读这俩字段（应当 0 引用）

#### Scenario: 前端缓存表头无 today_buy / today_sell 列

- **WHEN** admin 打开 `/admin/cache/positions`
- **THEN** `CachePositions.vue` 表格列定义不含 `today_buy` / `today_sell`

### Requirement: 持仓数据来源（v12 简化）

`Position` 数据的写入来源 MUST 简化为两条路径：`do_reconcile` 全表覆盖（broker 权威），`trd_cfm` push handler 盘中增量 `vol`（实时响应成交回报）。**不再**有"pos_cfm 写入路径"（broker 不发 pos_cfm）、**不再**有"today_buy/sell 写入路径"（字段已删）。

#### Scenario: 写入路径 2 条

- **WHEN** `Position` 行被改动
- **THEN** 写入方要么是 `do_reconcile`（开盘基准）、要么是 `_update_position_vol`（`trd_cfm` handler 内调）
- **AND** `Position.last_vol` / `Position.cost_price` 仅由 `do_reconcile` 写
- **AND** `Position.vol` 由 `do_reconcile` 写或被 `trd_cfm` 累加

### Requirement: 持仓调平客户端入口（v12）

前端 MUST 通过 `api.adjustPosition(stockCode, deltaVol, deltaAvlVol)` 调用调平，详见 `asset-position-adjust/spec.md`。UI 入口位置：`/admin/cache/positions` 表格行操作列加"调平"按钮。

#### Scenario: admin 调平 Position

- **WHEN** admin 在 `/admin/cache/positions` 点击某行"调平"按钮
- **THEN** 弹出输入框 `delta_vol` / `delta_avl_vol` / `reason`（reason 仅入 log）
- **AND** 提交时调用 `api.adjustPosition(stockCode, deltaVol, deltaAvlVol)`
- **AND** 成功后在表格中即时反映（前端 watcher 触发）—— 不依赖 re-fetch

## REMOVED Requirements

### Requirement: pos_cfm push handler 写入 Position.vol / avl_vol

**Reason**: xtquant broker 协议不发送 `pos_cfm`（详见 `consolidate-position-data-flow` 归档 + `push/spec.md:REQ-PUSH-031`）。`pos_cfm` handler 在前序 change 已删除，本 delta 仅清理 data-model 与 positioning spec 中残留的死描述。

**Migration**: 已删除，无需额外迁移。

### Requirement: Position.today_buy / today_sell 写入语义

**Reason**: 字段已从 `Position` 表删除（见 `data-model/spec.md` v12 修订）。

**Migration**: 当日买卖累计改由 `Trade` 表 SUM 聚合替代。
