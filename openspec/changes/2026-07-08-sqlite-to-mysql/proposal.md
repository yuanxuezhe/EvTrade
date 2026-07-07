# Proposal: SQLite → MySQL 8.0 迁移

**Change:** `2026-07-08-sqlite-to-mysql`
**Capability affected:** `configuration` / `data-model` / `server-architecture`
**Status:** draft (2026-07-08)

## Why

业务平台 EvTrade 当前用 SQLite 单文件存所有运行时数据（orders / trades / positions / assets / sys_status / users / strategy_trade）。SQLite 的局限已显形：

1. **单写并发** — FastAPI 异步多 worker 写同一 `.db` 文件会触发 `database is locked`（已通过 `check_same_thread=False` + PoolSize=1 掩盖）
2. **无网络访问** — hqserver / admin 工具想共享 DB 须依赖 db 文件拷贝
3. **无健康/运维可见性** — 没有连接池指标、没有慢查询、没有 replication

切到 MySQL 8.0 后所有这些问题一并解决：事务并发、网络共享（Docker 化）、标准运维工具。

## What

- 新增 `docker/mysql/` 服务（MySQL 8.0 LTS，端口 `33066` → 3306）
- 服务器用户权限：管理员 `root/p@ssw0rd`（仅容器内、不暴露端口）、业务库只读 `EvTrade/p@ssw0rd`（DML only，无 DDL）
- `server/infra/db.py` 改为读 `EVTRADE_DB_URL`（默认回退 SQLite，便于本地开发），URL 走 `.env`
- `requirements.txt` 添加 `pymysql + cryptography`（纯 Python 驱动，跨平台零编译）
- 现有 1 个 SQLite-compatible migration 改写为 MySQL 语法
- `evtrade.db` 数据一次性 dump → 走 EvTrade 用户 import 到 MySQL

## When NOT

- 用户处于开发分支并希望保留 SQLite 体验（本地零依赖），`.env` 可写回 `EVTRADE_DB_URL=sqlite:///...` 走 fallback
- 想加 Alembic / connection pool tuning / health endpoint —— 留待后续 PR，本 change 只做"最小可运行"

## 影响面

| 文件 | 改动 |
|---|---|
| `docker-compose.yml` | 加 mysql service (新建于 `docker/mysql/`) |
| `docker/mysql/init/01-create-user.sql` | 建 EvTrade 用户 + 业务库 `evtrade` |
| `docker/mysql/Dockerfile` | 基于 mysql:8.0，初始化时执行 SQL |
| `server/.env` / `.env.example` | 加 `EVTRADE_DB_URL` |
| `server/infra/db.py` | URL 改 ENV + pool 配置 |
| `server/migrations/2026-07-06-add-orders-raw-id.py` | SQLite 改 MySQL 兼容 |
| `requirements.txt` | + pymysql + cryptography |
| `scripts/migrate_sqlite_to_mysql.py` | 一次性数据迁移脚本（自动生成） |

合计：**8 个文件改动**（其中 1 个新建迁移脚本）

## 风险 + 缓解

参见 `tasks.md` §"Out-of-scope 风险"。

## DoD

- ✅ `docker compose up -d mysql` 容器起且 EvTrade 业务库就绪
- ✅ `scripts/migrate_sqlite_to_mysql.py` 从 `evtrade.db` 全量导数据
- ✅ `service backend start` 起来后 `GET /api/admin/sys-status` 返 200 且数据完整
- ✅ `service hqserver start` 起后台 + 不会尝试连 SQLite
- ✅ `python -m pytest server/test_*.py` 全过

## 关联文档

- specs: `configuration/spec.md` §"REQ-CFG-002" 加 REQ-CFG-009 DB URL
- specs: `data-model/spec.md` 加 REQ-DATA-MYSQL 表/字符集/索引约定
