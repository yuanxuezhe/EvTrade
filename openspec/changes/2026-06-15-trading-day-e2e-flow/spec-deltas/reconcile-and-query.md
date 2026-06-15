## ADDED Requirements

### Requirement: 日初切日必须更新到交易日表（TradingDay upsert）

`POST /api/admin/trading-day/init` 调用 `do_reconcile` 完成后，必须把对应 trd_date upsert 到 trading_day 表：
- **同 current_date 已存在行** → status='active', 更新 initialized_at/initialized_by
- **不存在** → INSERT 新行 (status='active', initialized_at=now, initialized_by=by_user)
- **若已有 status='active' 的行 且 current_date 不同** → 改其 status='closed'（切日）

#### Scenario: 同日多次 init 不累积
- 第一次 init 20260614 → trading_day 表 1 行 active
- 第二次 init 20260614 → trading_day 表仍 1 行 active（不是 2 行）

#### Scenario: 切到新日
- 第一次 init 20260614 → active 1 行
- 第二次 init 20260615 → 20260614 closed + 20260615 active（共 2 行）

#### Scenario: DB 唯一约束保护
- `UniqueConstraint("current_date", name="uq_trading_day_current_date")` 在表层防止同日 INSERT 多行
- 直接 INSERT 抛 IntegrityError

### Requirement: 日初必须从 RPC 拉数据并写入本地表

`do_reconcile` 流程：
1. 并行调 `qry_orders / qry_trades / qry_positions / qry_asset` 4 类 RPC
2. 写 `reconcile_report` 表（diffs_json / broker_asset_json / local_asset_json / broker_positions_json / local_positions_json / rpc_status / error_message）
3. **auto_reconcile=True** → `_apply_broker_data` 用柜台数据覆盖本地：
   - `db.query(Order).filter(TRD_DATE==trd_date).delete()` + 批量 INSERT
   - 同上 Trade / Position / Asset
4. **auto_reconcile=False** → 仅写报告，不动本地数据

#### Scenario: auto 模式覆盖本地
- mock RPC 返 order_id=10001, stock_code=600000.SH, status='56' (全成)
- do_reconcile 后，orders 表对应 TRD_DATE 查到该委托（status='56'）

#### Scenario: manual 模式不覆盖
- mock RPC 返 order_id=10001
- do_reconcile 后，orders 表对应 TRD_DATE 仍为空（仅报告有数据）

#### Scenario: RPC 全失败
- 4 类 RPC 全 raise
- 返回 ok=False, error 包含所有 RPC 错误
- 不切交易日（trading_day 表无新行）

#### Scenario: RPC 部分失败
- 2/4 RPC 失败
- 仍写报告（rpc_status='partial'）
- 返回 ok=False, error 包含失败详情
- 不切交易日

### Requirement: 查询路由必须查本地 DB（不调 RPC）

`GET /api/asset` / `GET /api/positions` / `GET /api/holdings` / `GET /api/orders` / `GET /api/trades` 全部走 `db.query(...).filter(TRD_DATE==trd_date)`，**不调任何 RPC 函数**。

#### Scenario: 日初后查资产
- do_reconcile 完成后，GET /api/asset 返 200 + data 来自 assets 表（不是 RPC 实时拉）
- 数据应 = RPC 返的 broker 端数据（因为 _apply_broker_data 覆盖了）

#### Scenario: 无资产数据
- 没有任何 push/reconcile 写入 → GET /api/asset 返 `{code: 0, data: null, msg: "无资产数据"}` (HTTP 200)
