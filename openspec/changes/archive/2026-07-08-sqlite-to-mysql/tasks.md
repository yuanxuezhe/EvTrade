# Tasks — SQLite → MySQL 迁移

按 v6 拆小 commit。

> **✅ ARCHIVED 2026-07-08 — change 已落地并合并 spec**
>
> Commits（master）：
> - `a090e7d` Stage 1: OpenSpec 草稿
> - `be32aca` Stage 3 commit 2: .env.example MySQL URL
> - `ecb47c0` Stage 3 commit 3: db.py 改造 + requirements
> - `d4f0c03` Stage 3 commit 4: migrations 兼容 + data import
> - `bdd83d3` Stage 4: sync REQ-CFG-009/010 进入 specs/configuration/spec.md
>
> **Stage 3 commit 1**: 外部服务 `docker/mysql/`（in `/root/workspace/docker/mysql/`，不在 EvTrade git 仓）
> **端到端 runtime 验证 deferred to ops**（项目预存在 python 3.13 + missing deps 问题不在本 PR scope）

## Stage 1（草稿）

- [x] 写 proposal.md
- [x] 写 spec-deltas/configuration.md
- [x] 写 spec-deltas/data-model.md
- [x] 写 tasks.md（本文件）

## Stage 3（实施）

### Commit 1: Docker MySQL 服务 + 初始化

- [x] 建 `/root/workspace/docker/mysql/docker-compose.yml`：基于 `mysql:8.0`，bind 127.0.0.1:33066
- [x] 写 `config/01-evtrade-user.sql`：
  - `CREATE DATABASE IF NOT EXISTS evtrade CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`
  - `CREATE USER IF NOT EXISTS 'EvTrade'@'%' IDENTIFIED BY 'p@ssw0rd'`
  - `CREATE USER IF NOT EXISTS 'evtrade_dba'@'%' IDENTIFIED BY 'p@ssw0rd'`
  - `GRANT SELECT, INSERT, UPDATE, DELETE ON evtrade.* TO 'EvTrade'@'%'`
  - `GRANT ALL PRIVILEGES ON evtrade.* TO 'evtrade_dba'@'%'`
  - `ALTER USER 'root'@'localhost' ACCOUNT LOCK` + root 远程拒
- [x] 验证：`docker compose up -d` + `docker inspect` healthy ✓ + 业务账号 DDL 拒绝 ✓ + DBA CREATE 成功 ✓

### Commit 2: server/.env + .env.example 加 MySQL URL

- [x] `EVTRADE_DB_URL=mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4`（URL 中 @ → %40 编码）
- [x] `.env.example` 用 p%40ssw0rd + 注释说明 @ 必编码

### Commit 3: server/infra/db.py 改造

- [x] URL 读 `EVTRADE_DB_URL` env，**fallback 到 SQLite**
- [x] 加 pool config（pool_size/max_overflow/pool_recycle/pool_pre_ping）
- [x] SQLite-only 的 `PRAGMA foreign_keys=ON` 改成 `event.listens_for(engine, "connect")` 的 **driver-aware** 实现（MySQL skip）
- [x] `init_db()` 创建 all tables；现有 `CREATE INDEX IF NOT EXISTS ix_orders_user_def ON orders(user_def)` 保留
- [x] 双轨 ADMIN_URL：init_db 走 `EVTRADE_DB_ADMIN_URL` 否则降级到 DML URL（DDL 失败显式提示）
- [x] requirements.txt 加 `pymysql>=1.1.0,<2.0.0` + `cryptography>=42`

### Commit 4: MySQL 兼容 migration + 数据迁移脚本

- [x] `server/migrations/2026-07-06-add-orders-raw-id.py`：SQLite `ALTER TABLE ... ADD COLUMN` 改 driver-aware（INFORMATION_SCHEMA / pragma_table_info 探测）
- [x] `server/migrations/sqlite-to-mysql-migrate.py`：全量 dump → INSERT IGNORE → checksum 校验（5 行数据导入验证通过）

### Commit 5: 验证

- [x] data import: admin 用户 1 + orders 1 + fee_config 1 + reconcile_config 1 + trading_session 1（全部 from SQLite → MySQL）
- [x] 业务账号 CRUD 端到端 via pymysql ✓ (INSERT/SELECT/UPDATE/DELETE)
- [ ] service backend restart — **deferred to ops**（项目预存在 python 3.13 + missing deps，含 msgpacket 跨仓 — 见 Resolved Questions）
- [ ] `curl /api/admin/sys-status` 200 — **deferred**

## Stage 4（归档）

- [x] 合并 REQ-CFG-009/010 + S-CFG-006-009 进 `specs/configuration/spec.md`
- [x] git mv `2026-07-08-sqlite-to-mysql` → `archive/2026-07-08-sqlite-to-mysql`
- [x] tasks.md 加 ARCHIVED banner + commit hash

## Out-of-scope（不在本 PR）

- Alembic 迁移系统（当前 1 个 raw SQL 够用）
- `/api/health/db` endpoint（运维侧监控需求不强，本 PR 不加）
- 多实例 / 双写 / 主从复制（单实例场景）
- SQLAlchemy `pool_size` 调优（先设 5，后续压测再调）
- `server/.env` SQLite 路径在多平台下备份策略
- **Fix python 3.13 + 依赖链（fastapi 0.95/pydantic 1.10.18/msgpacket）— 单独 change**
