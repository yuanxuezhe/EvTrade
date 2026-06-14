# Spec Delta — persistence-and-t0 → configuration

## ADDED Requirements

### REQ-CFG-007: 交易日状态机

- `trading_day` 表（已实现模式）
- 状态：`pending`（切了但未对账） / `active`（已激活） / `closed`（已收市）
- 同一时刻最多 1 行 `active`
- 切换流程：旧 `active → closed` + 新行 `active`
- 屏障：`require_trading_day` 依赖此表

### REQ-CFG-008: 交易时段屏障

- `trading_session` 表（单行）
- 字段：`morning_start='09:15'` / `morning_end='11:30'` / `afternoon_start='13:00'` / `afternoon_end='15:00'`
- 服务：`services/trading_clock.py` 缓存 60s 判断 `is_in_trading_session`
- 屏障：`require_trading_session` 用于下单/撤单
- 节假日/半天支持：`trading_day.is_half_day`（默认 0）
- 时段可配置：admin `PATCH /api/admin/trading-session`

### REQ-CFG-009: 日初对账（人工触发）

- `POST /api/admin/trading-day/init` 触发
- 输入：`{trading_date, auto_reconcile?}`
- 流程：
  1. 取 `reconcile_config`（auto_reconcile / auto_use_broker_data）
  2. RPC 并行：qry_asset + qry_pos + qry_orders + qry_mch
  3. 算 diff
  4. auto_reconcile=True → 覆盖本地 4 张表
  5. auto_reconcile=False → 写 `reconcile_report`，不动数据
  6. RPC 失败 → 503 + 错误明细 + **不切交易日**
  7. 成功 → 关闭旧 active + 新增 active 行
- 可重做：失败后用户点"重试"

### REQ-CFG-010: 启动不主动对账

- main.py 启动时**不**调对账
- 完全依赖用户人工触发 `POST /api/admin/trading-day/init`
- 启动只做：DB 初始化 + 启动 RPC listener + 启动 hqserver

### REQ-CFG-011: 默认查询交易日

- 函数 `resolve_default_trd_date(db) -> str`
- 逻辑：
  1. `SELECT * FROM trading_day WHERE status='active'` → 有则用 `current_date`
  2. 否则 `SELECT MAX(TRD_DATE) FROM orders` → 有则用
  3. 否则 `datetime.now().strftime('%Y%m%d')`
- API 接受 `?trading_day=YYYYMMDD` 覆盖

## MODIFIED Requirements

### REQ-CFG-001（兼容保留）

- `.env` 仍由 `config.py` 读取
- 必填项校验仍由后续 `add-config-validation` change 处理
- 本 change 不修改 config.py
