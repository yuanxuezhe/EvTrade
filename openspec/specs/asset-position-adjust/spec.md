## Purpose

管理员对 `Asset` / `Position` 表做盘中调平补丁：手动调整资金总量 / 资金可用 / 持仓总量 / 持仓可用，绕开对账窗口内的延迟。**调平值在下次 `do_reconcile` 全表覆盖时被抹掉**，定位为临时补丁。

## Requirements

### Requirement: Asset 调平 API（v12 新增）

The system SHALL 提供 `PUT /api/asset/adjust` 端点让 admin 资金盘中调平资金总量（total_asset）/ 资金可用（cash）。

- **端点路径**：`PUT /api/asset/adjust`
- **鉴权**：role=admin
- **请求体 Pydantic**：`AdjustAssetRequest { delta_cash?: float, delta_total_asset?: float, reason?: str }`
  - 至少传一个 `delta_*` 字段，否则 422
  - `reason` 仅入 log，不入库（用户明确不留 audit）
- **响应**：`{ code: 0, msg: "ok", asset: AssetOut }`
- **副作用**：
  - `Asset.cash` ← `Asset.cash + delta_cash`（若有）
  - `Asset.total_asset` ← `Asset.total_asset + delta_total_asset`（若有）
  - `Asset.synced_from` ← `"manual"`
  - `Asset.synced_at` ← `utcnow()`
  - `db.commit()`

#### Scenario: 调增 cash 成功

- **WHEN** admin 调 `PUT /api/asset/adjust { delta_cash: 1000.0, reason: "银证转账入金" }`
- **THEN** 响应 `200 OK` + `{ code: 0, msg: "ok", asset: { cash: 6000.0, ... } }`（假设原 cash=5000）
- **AND** 服务端 log 记录 "admin={user_id} reason=银证转账入金 delta_cash=1000.0 new_cash=6000.0"

#### Scenario: 调减 cash 允许负值

- **WHEN** admin 调 `PUT /api/asset/adjust { delta_cash: -800.0 }` 且原 `cash=500.0`
- **THEN** `cash = -300.0`（broker 真实可透支场景）
- **AND** 不抛 ValueError

#### Scenario: 缺字段返 422

- **WHEN** admin 调 `PUT /api/asset/adjust {}`
- **THEN** Pydantic 校验失败，返 422

#### Scenario: 非 admin 返 403

- **WHEN** trader 调 `PUT /api/asset/adjust { delta_cash: 1000.0 }`
- **THEN** 返 403 `{ code: FORBIDDEN, msg: "admin role required" }`

### Requirement: Position 调平 API（v12 新增）

The system SHALL 提供 `PUT /api/positions/{stock_code}/adjust` 端点让 admin 调平持仓总量（vol）/ 持仓可用（avl_vol）。

- **端点路径**：`PUT /api/positions/{stock_code}/adjust`
- **鉴权**：role=admin
- **请求体 Pydantic**：`AdjustPositionRequest { delta_vol?: int, delta_avl_vol?: int, reason?: str }`
- **响应**：`{ code: 0, msg: "ok", position: PositionOut }`
- **副作用**（位置由 URL path 定位）：
  - 查 `Position.stock_code == stock_code` —— 不存在则 404
  - `Position.vol` ← `Position.vol + delta_vol`
  - `Position.avl_vol` ← `Position.avl_vol + delta_avl_vol`
  - `Position.synced_from` ← `"manual"`
  - `Position.synced_at` ← `utcnow()`
  - `db.commit()`

#### Scenario: 调增 vol 成功

- **WHEN** admin 调 `PUT /api/positions/600030.SH/adjust { delta_vol: 100, reason: "期权行权" }`
- **AND** Position row 已存在（trd_code = 600030.SH）
- **THEN** `Position.vol += 100`
- **AND** 响应 `{ code: 0, msg: "ok", position: { vol: 200, ... } }`（假设原 vol=100）

#### Scenario: avl_vol 不传则不动

- **WHEN** admin 仅传 `delta_vol`，未传 `delta_avl_vol`
- **THEN** `Position.avl_vol` 保持不变

#### Scenario: stock_code 不存在的 Position

- **WHEN** admin 调 `PUT /api/positions/UNKNOWN/adjust { delta_vol: 100 }`
- **THEN** 返 404 `{ code: POSITION_NOT_FOUND, msg: "no Position for stock_code=UNKNOWN" }`
- **AND** 不自动新建行（防误操作）

#### Scenario: 非 admin 返 403

- **WHEN** trader 调 `PUT /api/positions/600030.SH/adjust { delta_vol: 100 }`
- **THEN** 返 403

### Requirement: 客户端 API 封装（v12）

`client/src/api/index.js` MUST 导出：

- `api.adjustAsset({ deltaCash, deltaTotalAsset, reason })` —— `PUT /api/asset/adjust`
- `api.adjustPosition(stockCode, { deltaVol, deltaAvlVol, reason })` —— `PUT /api/positions/${stockCode}/adjust`

#### Scenario: adjustPosition 封装正确性

- **WHEN** 前端调 `api.adjustPosition("600030.SH", { deltaVol: 100, reason: "期权行权" })`
- **THEN** axios PUT 到 `BASE_URL/api/positions/600030.SH/adjust`
- **AND** body = `{ delta_vol: 100, reason: "期权行权" }`（snake_case 字段名）
- **AND** 响应拦截器解包 `code=0` 后 `resolve(asset)`

### Requirement: 不引入 manual_offset_* 字段（边界约束）

The system SHALL NOT 在 `Position` / `Asset` 表新增 `manual_offset_*` 列 —— 调平值直接体现在 `vol` / `avl_vol` / `cash` / `total_asset` 上，无独立 delta 字段。

#### Scenario: grep 自检

- **WHEN** 实施完成时静态扫 `server/models/orm.py`
- **THEN** grep -rE 'manual_offset_(vol|avl_vol|cash|total_asset)' 应 0 命中

#### Scenario: 不引入 AdjustAudit 子表

- **WHEN** 实施完成时
- **THEN** DB schema 不含 `adjust_audit` / `manual_adjust_log` 子表
- **AND** reconcile_report 中也不出现 manual adjust 行

### Requirement: 调平值的生命周期（窗口边界）

The system SHALL 接受调平值在下一次 `do_reconcile` 全表覆盖时被抹掉 —— 调平是 reconcile 之间的临时补丁。

#### Scenario: reconcile 后调平消失

- **WHEN** admin 调平 `Position.vol += 100`
- **AND** 后续 `do_reconcile` 执行（broker 端真实 vol = 真实值）
- **THEN** `Position.vol` 被 broker 真实值覆盖
- **AND** `Position.synced_from = "rpc_full"`（不再 `"manual"`）
- **AND** UI 提示 admin 此行已被 reconcile 覆盖
