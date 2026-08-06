# Spec Delta — v20 (REQ-TEST-006, REQ-DB-008, REQ-FE-013)

## REQ-TEST-006: pytest fixture 模块化 + 时段感知

**Add** to `openspec/specs/testing/spec.md`:

### 测试基础设施要求

- **业务 DB 测试**: `pytest --tb=short` 必须 exit 0。e2e 套件允许 `pytest.skip()` 但不允许 `ERROR` (除环境本身故障)
- **市场时段感知**: 下单/撤单 e2e 在非交易时段 (收市后 / 周末) 必须 `pytest.skip()` 而非断言失败
  - 判定标准: 服务端 `require_trading_session` 装饰器返 503 OUTSIDE_TRADING_SESSION 即视为收市信号
  - 实施: 测试框架加 `check(skip=...)` 标记，503 时跳过
- **fixture 隔离**: 测试不破坏 `users` / `sys_status` / `trading_session` 等系统配置表
  - 软清策略: per-test 清业务表数据，module-level 全量 init_db
  - 白名单保留 9 张系统表

### 已知 v21 backlog

- segfault on `trd_cfm` push (libc.so.6 AVX) — v20 不修，记录为已知问题
- 真 RPC mock 取代 skip — v21+

## REQ-DB-008: 连接池驱动独立 kwargs

**Modify** `openspec/specs/database/spec.md` (DB 连接池章节):

- SQLite 与 MySQL admin engine 必须**独立**计算 `pool_kwargs`：
  - SQLite: `connect_args={"check_same_thread": False}`
  - MySQL: `connect_args={}` + 标准 pool
- 禁止从一个 engine 的 kwargs 复用给另一 engine（避免 SQLite-only kwargs 污染 MySQL）
- 验证: `init_db()` 后 admin user 必须可登录（不复用 SQLite 误传 kwargs）

## REQ-FE-013: 后端响应字段契约（前端必须对齐）

**Add** to `openspec/specs/api/spec.md` (响应格式章节):

- 后端 OverviewResponse (聚合统计) 是**扁平**字段:
  - `active_task_count` (int)
  - `total_realized_pnl` (decimal)
  - `avg_win_rate` (float, 0.0~1.0)
  - `total_commission`, `total_stamp_tax`, `total_trading_days`
  - `closed_task_count`, `archived_task_count`, `total_unrealized_pnl`
- 前端禁止用 `{ overall: {...} }` 嵌套读取 — 模板必须直接读扁平字段
- Pinia store 默认值必须 `{}` 而非带结构的占位符（否则空数据触发 undefined 读取）