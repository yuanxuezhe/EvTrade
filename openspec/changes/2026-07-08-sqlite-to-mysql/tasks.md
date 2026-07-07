# Tasks — SQLite → MySQL 迁移

按 v6 拆小 commit。

## Stage 1（草稿）

- [x] 写 proposal.md
- [x] 写 spec-deltas/configuration.md
- [x] 写 spec-deltas/data-model.md
- [x] 写 tasks.md（本文件）

## Stage 3（实施）

### Commit 1: Docker MySQL 服务 + 初始化

- [ ] 建 `docker/mysql/Dockerfile`：基于 `mysql:8.0`，`COPY init/01-create-user.sql /docker-entrypoint-initdb.d/`
- [ ] 写 `docker/mysql/init/01-create-user.sql`：
  - `CREATE DATABASE IF NOT EXISTS evtrade CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`
  - `CREATE USER IF NOT EXISTS 'EvTrade'@'%' IDENTIFIED BY 'p@ssw0rd'`
  - `GRANT SELECT, INSERT, UPDATE, DELETE ON evtrade.* TO 'EvTrade'@'%'`
  - `FLUSH PRIVILEGES`
- [ ] 写 `docker-compose.yml`：mysql service healthcheck + bind 127.0.0.1:33066:3306
- [ ] 验证：`docker compose up -d mysql && docker compose ps` 显示 healthy

### Commit 2: server/.env + .env.example 加 MySQL URL

- [ ] `EVTRADE_DB_URL=mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4`
- [ ] `.env.example` 用 `<SET_IN_ENV>` 脱敏

### Commit 3: server/infra/db.py 改造

- [ ] URL 读 `EVTRADE_DB_URL` env，**fallback 到 SQLite**
- [ ] 加 pool config（pool_size/max_overflow/pool_recycle/pool_pre_ping）
- [ ] SQLite-only 的 `PRAGMA foreign_keys=ON` 改成 `event.listens_for(engine, "connect")` 的 **driver-aware** 实现（MySQL skip）
- [ ] `init_db()` 创建 all tables；现有 `CREATE INDEX IF NOT EXISTS ix_orders_user_def ON orders(user_def)` 保留

### Commit 4: MySQL 兼容 migration + 数据迁移脚本

- [ ] `server/migrations/2026-07-06-add-orders-raw-id.py`：SQLite `ALTER TABLE ... ADD COLUMN` 改 MySQL 兼容（MySQL 不支持 `IF NOT EXISTS` on ADD COLUMN，要先 `INFORMATION_SCHEMA` 查）
- [ ] 新 `scripts/migrate_sqlite_to_mysql.py`：脚本全量 dump → import → checksum 校验
- [ ] `requirements.txt` + `pymysql==1.1.x` + `cryptography>=41`

### Commit 5: 验证

- [ ] `service backend restart` 不挂
- [ ] `curl localhost:8000/api/admin/sys-status` 返 200（非空）
- [ ] 旧数据校验：用户 / 持仓 / 委托 / 成交 行数与 SQLite 一致

## Stage 4（归档）

- [ ] /opsx:sync 把 spec-deltas 合并进 `specs/{configuration,data-model}/spec.md`
- [ ] /opsx:archive 移 `2026-07-08-sqlite-to-mysql` → `archive/`

## Out-of-scope（不在本 PR）

- Alembic 迁移系统（当前 1 个 raw SQL 够用）
- `/api/health/db` endpoint（运维侧监控需求不强，本 PR 不加）
- 多实例 / 双写 / 主从复制（单实例场景）
- SQLAlchemy `pool_size` 调优（先设 5，后续压测再调）
- `server/.env` SQLite 路径在多平台下备份策略
