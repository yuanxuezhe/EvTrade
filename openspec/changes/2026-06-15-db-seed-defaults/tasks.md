# Tasks: DB seed defaults

## Phase 1: 代码改动

- [ ] **T1.1** 修改 `server/db.py:init_db()`，在 `Base.metadata.create_all` 之后调用
  `seed_default_admin()` 和 `seed_default_config()`
- [ ] **T1.2** 在 `server/db.py` 新增 `seed_default_admin()` 函数
  - import User, hash_password
  - `SELECT COUNT(*) FROM users` → 0 时插入 admin/admin123
  - 打印 `[SEED] Created default admin: admin / admin123`
- [ ] **T1.3** 在 `server/db.py` 新增 `seed_default_config()` 函数
  - import TradingSession, FeeConfig, ReconcileConfig, OrderNoSeq
  - 4 张表分别 count==0 时插入单行
  - 4 条 `[SEED]` 日志
  - **不** seed trading_day
- [ ] **T1.4** 简化 `server/main.py:on_startup`
  - 删除内联的 admin 创建逻辑（22 行）
  - 仅保留 `init_db()` 调用
  - 删 unused imports: `User, hash_password, SessionLocal`

## Phase 2: 验证

- [ ] **T2.1** 删 `server/evtrade.db`，`scripts/restart.sh restart`
- [ ] **T2.2** 验证启动日志含 5 行 `[SEED]`
- [ ] **T2.3** SQLite 直查 5 张表各有 1 行
- [ ] **T2.4** `curl POST /api/auth/login admin/admin123` 返 200
- [ ] **T2.5** TradingDay 表仍为空（验证未自动 seed）
- [ ] **T2.6** `PATCH /api/fee-config` 改值 → restart → 值保留（幂等性）
- [ ] **T2.7** 跑 `pytest server/test_models.py test_guards.py test_reconcile.py` 全绿

## Phase 3: 归档

- [ ] **T3.1** commit: `feat(config): db 默认数据 seed 集中到 init_db()`
- [ ] **T3.2** 把 spec-delta 合并到 `specs/configuration/spec.md`
- [ ] **T3.3** `mv openspec/changes/2026-06-15-db-seed-defaults openspec/changes/archive/`
- [ ] **T3.4** 更新 `openspec/AGENTS.md` 活跃 change 表格

## Out of Scope (deferred to v6)

- TradingDay 自动激活（cron + RPC health check）
- 测试 fixture 临时 db 隔离（v4 弱点）
- min_commission 路由暴露

## Risks

- pytest 与运行 backend 共享 evtrade.db 文件名（v4 已知）
- SQLAlchemy 多实例并发 seed race（SQLite 已知，不处理）
